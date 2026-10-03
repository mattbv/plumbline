"""The `plumb` CLI (PRD §6 J1, §8.1-8.4).

M0 scaffold: `plumb init` is real end-to-end (creates a config file and an
Ontolith-backed KB with the schema applied). `ingest` and `drift` are real:
`ingest` replays a Git repository's history into the knowledge base, resumably, and
reports what it deliberately left alone; `drift` lists the open contradictions. `explain`/
`as-of`/`blame`/`check` are wired with the right arguments and help text but raise
`NotImplementedError` -- they're M1 work (PRD §10).
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from plumbline import __version__
from plumbline.adapters.git_reader import GitError
from plumbline.adapters.ontolith_kb import OntolithKnowledgeBase
from plumbline.application.drift import DriftItem
from plumbline.application.ports import CommitRef
from plumbline.application.use_cases.backfill import HistoryRewritten, IngestTotals
from plumbline.application.use_cases.ingest import IngestReport
from plumbline.interfaces.pipeline import open_pipeline

app = typer.Typer(
    name="plumb",
    help="Governed, bitemporal reconciliation between a codebase and its documentation.",
    no_args_is_help=True,
)

CONFIG_FILENAME = "plumbline.toml"
DEFAULT_KB_FILENAME = ".plumbline/kb.db"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"plumb {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool, typer.Option("--version", callback=_version_callback, is_eager=True)
    ] = False,
) -> None:
    """Plumbline: keep your docs honest about your code."""


@app.command()
def init(
    admin: Annotated[str, typer.Option(help="Your principal id, e.g. an email address.")],
    path: Annotated[Path, typer.Option(help="Repository root to initialize in.")] = Path(),
) -> None:
    """Create plumbline.toml and a fresh knowledge base (PRD J1, step 1)."""
    config_path = path / CONFIG_FILENAME
    kb_path = path / DEFAULT_KB_FILENAME
    if config_path.exists():
        typer.echo(f"{config_path} already exists -- refusing to overwrite.", err=True)
        raise typer.Exit(code=1)

    kb_path.parent.mkdir(parents=True, exist_ok=True)
    OntolithKnowledgeBase.initialize(kb_path, admin_principal_id=admin).close()

    config_path.write_text(
        f"# Plumbline configuration (PRD §8.1 ING-10).\n"
        f'kb_path = "{DEFAULT_KB_FILENAME}"\n'
        f'admin = "{admin}"\n'
        f'tracked_branch = "main"\n\n'
        f"[sources]\n"
        f'readme = ["README*.md"]\n'
        f'docs = ["docs/**/*.md"]\n'
        f'changelog = ["CHANGELOG.md"]\n',
        encoding="utf-8",
    )
    typer.echo(f"Created {config_path} and {kb_path}.")


def _load_config(path: Path) -> dict[str, object]:
    config_path = path / CONFIG_FILENAME
    if not config_path.exists():
        typer.echo(f"No {CONFIG_FILENAME} found -- run `plumb init` first.", err=True)
        raise typer.Exit(code=1)
    with config_path.open("rb") as f:
        return tomllib.load(f)


STATE_SUFFIX = ".ingest.json"


def _resolve_kb(path: Path, kb: Path | None, *, must_exist: bool) -> Path:
    """The KB file: ``--kb``, else ``kb_path`` from ``plumbline.toml`` under ``path``."""
    if kb is None:
        if not (path / CONFIG_FILENAME).exists():
            typer.echo(f"Pass --kb, or run `plumb init` in {path} first.", err=True)
            raise typer.Exit(code=1)
        kb = path / str(_load_config(path).get("kb_path", DEFAULT_KB_FILENAME))
    if must_exist and not kb.exists():
        typer.echo(f"No knowledge base at {kb}.", err=True)
        raise typer.Exit(code=1)
    return kb


def _read_state(state_path: Path) -> dict[str, object] | None:
    return json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else None


def _write_state(state_path: Path, state: dict[str, object]) -> None:
    """Replace the state file atomically, so an interrupted run never leaves it half-written."""
    temp = state_path.with_suffix(state_path.suffix + ".tmp")
    temp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, state_path)


def _print_totals(totals: IngestTotals, *, resumed: bool) -> None:
    typer.echo(f"\nIngested {totals.commits} commit(s){' (resumed)' if resumed else ''}.")
    rows = [
        ("code facts written", totals.l1_writes),
        ("symbols removed", totals.removed),
        ("code facts withdrawn (no longer stated)", totals.fields_withdrawn),
        (
            "doc claims asserted / retracted",
            f"{totals.claims_asserted} / {totals.claims_retracted}",
        ),
        ("projections stated / withdrawn", f"{totals.projected} / {totals.projections_withdrawn}"),
    ]
    for label, value in rows:
        typer.echo(f"  {label:<42}{value}")
    typer.echo("Left alone, on purpose:")
    typer.echo(f"  {'abstentions (code value unprovable)':<42}{totals.abstained}")
    typer.echo(f"  {'symbol-key ownership conflicts':<42}{totals.conflicts}")
    typer.echo(f"  {'changes deferred under a dispute':<42}{totals.deferred}")
    typer.echo(f"  {'files not analysed (e.g. syntax error)':<42}{len(totals.unanalyzed)}")


@app.command()
def ingest(
    path: Annotated[Path, typer.Option(help="Project root holding plumbline.toml.")] = Path(),
    repo: Annotated[
        Path | None, typer.Option(help="Git repository to read (default: --path).")
    ] = None,
    kb: Annotated[
        Path | None, typer.Option(help="Knowledge base file (default: plumbline.toml).")
    ] = None,
    branch: Annotated[str | None, typer.Option(help="Branch to follow (default: HEAD).")] = None,
    since: Annotated[
        str | None,
        typer.Option(
            help="Only history from this ISO date; the first commit then carries the whole tree."
        ),
    ] = None,
    limit: Annotated[int | None, typer.Option(help="Stop after this many commits.")] = None,
    exclude: Annotated[
        list[str] | None, typer.Option(help="Extra path pattern to ignore (repeatable).")
    ] = None,
    admin: Annotated[
        str, typer.Option(help="Admin principal if the KB must be created.")
    ] = "plumbline@localhost",
    report: Annotated[Path | None, typer.Option(help="Also write the totals as JSON.")] = None,
) -> None:
    """Replay the tracked branch's history into the knowledge base (PRD J1 step 2, ING-8).

    Resumable: run it again and it continues after the last commit it finished. Backfill
    goes into a fresh KB only; the repository is only ever read.
    """
    repo_root = (repo or path).resolve()
    kb_path = _resolve_kb(path, kb, must_exist=False)
    state_path = kb_path.with_name(kb_path.name + STATE_SUFFIX)
    window = None if since is None else datetime.fromisoformat(since).replace(tzinfo=UTC)

    state = _read_state(state_path)
    if state is not None and (state["repo"], state["branch"], state["since"]) != (
        str(repo_root),
        branch,
        since,
    ):
        typer.echo(
            f"{state_path} belongs to a different run (repo, branch, or --since differ).", err=True
        )
        raise typer.Exit(code=1)

    existed = kb_path.exists()
    pipeline = open_pipeline(repo_root, kb_path, admin=admin, branch=branch, exclude=exclude or ())
    store, backfill = pipeline.kb, pipeline.backfill
    if existed and state is None and not store.is_empty():
        store.close()
        typer.echo(
            "That KB already holds data from outside `plumb ingest`; "
            "backfill goes into a fresh KB.",
            err=True,
        )
        raise typer.Exit(code=1)

    last = None if state is None else state["last_sha"]
    done = 0 if state is None else int(str(state["commits"]))

    def checkpoint(commit: CommitRef, _report: IngestReport) -> None:
        nonlocal done
        done += 1
        _write_state(
            state_path,
            {
                "repo": str(repo_root),
                "branch": branch,
                "since": since,
                "last_sha": commit.sha,
                "commits": done,
            },
        )
        if done % 10 == 0:
            typer.echo(f"  {done} commits...", err=True)

    try:
        totals = backfill.run(after=last, since=window, limit=limit, on_commit=checkpoint)  # type: ignore[arg-type]
    except HistoryRewritten:
        typer.echo("The commit a previous run stopped at is no longer on the branch.", err=True)
        raise typer.Exit(code=1) from None
    except GitError as err:
        typer.echo(f"git: {err}", err=True)
        raise typer.Exit(code=1) from None
    finally:
        store.close()

    _print_totals(totals, resumed=state is not None)
    if report is not None:
        report.write_text(
            json.dumps({**asdict(totals), "unanalyzed": sorted(totals.unanalyzed)}, indent=2)
            + "\n",
            encoding="utf-8",
        )


def _print_drift(items: list[DriftItem], limit: int) -> None:
    by_class: dict[str, int] = {}
    for item in items:
        by_class[item.drift_class.value] = by_class.get(item.drift_class.value, 0) + 1
    typer.echo(
        f"{len(items)} open contradiction(s): "
        + ", ".join(f"{n} {k}" for k, n in sorted(by_class.items()))
        + "\n"
    )
    for rank, item in enumerate(items[:limit], start=1):
        opened = "" if item.opened_at is None else f", opened {item.opened_at:%Y-%m-%d}"
        typer.echo(f"{rank:>3}. {item.fact_key}  [{item.drift_class.value}{opened}]")
        for claim in sorted(item.claims, key=lambda c: (c.author != "plumb-projector", c.author)):
            who = (
                "code" if claim.author == "plumb-projector" else claim.author.removeprefix("plumb-")
            )
            typer.echo(f"       {who:<10} {claim.value!r:<28} {claim.path}")
    if len(items) > limit:
        typer.echo(f"\n... and {len(items) - limit} more (use --limit).")


@app.command()
def drift(
    path: Annotated[Path, typer.Option()] = Path(),
    kb: Annotated[
        Path | None, typer.Option(help="Knowledge base file (default: plumbline.toml).")
    ] = None,
    limit: Annotated[int, typer.Option(help="How many findings to show.")] = 20,
) -> None:
    """List open contradictions, strongest first (PRD J1 step 3)."""
    store = OntolithKnowledgeBase.open(_resolve_kb(path, kb, must_exist=True))
    try:
        items = store.open_drift()
    finally:
        store.close()
    if not items:
        typer.echo("No open contradictions.")
        return
    _print_drift(items, limit)


@app.command()
def explain(
    fact: Annotated[str, typer.Argument(help="A Fact's natural key or a symbol path.")],
    path: Annotated[Path, typer.Option()] = Path(),
) -> None:
    """Show a fact's every claim, provenance, and current status (PRD QRY-1)."""
    _load_config(path)
    raise NotImplementedError("M1: one Ontolith provenance() call per assertion (PRD QRY-1).")


@app.command(name="as-of")
def as_of(
    when: Annotated[str, typer.Argument(help="A release tag, commit SHA, or ISO datetime.")],
    page: Annotated[str | None, typer.Option(help="Scope to one doc page.")] = None,
    path: Annotated[Path, typer.Option()] = Path(),
) -> None:
    """Reconstruct what was known and true at a point in time (PRD QRY-2)."""
    _load_config(path)
    raise NotImplementedError("M1: Ontolith kb.as_of(t) reconstruction (PRD QRY-2).")


@app.command()
def blame(
    fact: Annotated[str, typer.Argument()],
    path: Annotated[Path, typer.Option()] = Path(),
) -> None:
    """Show a fact's introducing commit, detection, and resolution (PRD QRY-3)."""
    _load_config(path)
    raise NotImplementedError("M1: PRD QRY-3.")


@app.command()
def check(
    path: Annotated[Path, typer.Option()] = Path(),
    severity: Annotated[str, typer.Option(help="Minimum severity to fail on.")] = "error",
) -> None:
    """CI gate: exit non-zero only on drift introduced by this change (PRD REC-7)."""
    _load_config(path)
    raise NotImplementedError("M1: shadow-KB diff against main (PRD §7.7, REC-7).")
