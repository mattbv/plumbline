"""The `plumb` CLI (PRD §6 J1, §8.1-8.4).

M0 scaffold: `plumb init` is real end-to-end (creates a config file and an
Ontolith-backed KB with the schema applied). `ingest`/`drift`/`explain`/
`as-of`/`blame`/`check` are wired as real subcommands with the right
arguments and help text, but raise `NotImplementedError` -- they're M1 work
(PRD §10), and the point of stubbing them now is so the CLI's own shape
(what a command is called, what it takes) is settled and testable before
any of them do anything.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Annotated

import typer

from plumbline import __version__
from plumbline.adapters.ontolith_kb import OntolithKnowledgeBase

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


@app.command()
def ingest(
    backfill: Annotated[
        str | None, typer.Option(help='Replay history, e.g. "12mo" (PRD ING-8).')
    ] = None,
    path: Annotated[Path, typer.Option()] = Path(),
) -> None:
    """Ingest the tracked branch's history into the knowledge base (PRD J1 step 2)."""
    _load_config(path)
    raise NotImplementedError("M1: RepoReader + CodeImporter + DocImporter wiring (PRD §10 M1).")


@app.command()
def drift(path: Annotated[Path, typer.Option()] = Path()) -> None:
    """List open contradictions, grouped and ranked (PRD J1 step 3)."""
    _load_config(path)
    raise NotImplementedError("M1: reads Fact.value contradictions via KnowledgeBase (PRD DRF-1).")


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
