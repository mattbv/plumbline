"""Seeded-drift measurement: inject known drift into real code and see what Plumbline finds.

Zero findings on a well-kept project looks the same as a tool that cannot see anything. So
this injects drift whose answer is known and checks that every injection is found and that
nothing else is.

How it works, so the result can be trusted:

* It works on a **scratch clone** of the repository; the original is only read.
* The baseline history is ingested once with the same pipeline `plumb ingest` uses
  (`plumbline.interfaces.pipeline`). Each injection is then a **real Git commit** that is
  ingested incrementally, and any contradiction that is *new* afterwards is attributed to it.
* Injections are chosen from the tool's own corroborated claims and made with the AST
  (`evaluation.mutations`), on both sides: code drifting from the docs, and docs drifting
  from the code.
* **Controls** are edits that must *not* be reported (a comment, an undocumented change, a
  reworded summary). They measure false positives on real code under churn.
* **By-design blind spots** (a removed ``raise`` can never be proven absent) are reported
  separately, and are not counted as misses.

Usage::

    python -m evaluation.seeded_drift --repo PATH [--per-category 10] [--seed 1] \
        [--workdir DIR] [--report FILE]
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import random
import shutil
import subprocess
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from pathlib import Path

from plumbline.adapters._pysource import module_name
from plumbline.application.drift import DriftItem
from plumbline.application.projection import PROJECTOR_PRINCIPAL
from plumbline.domain import canonical
from plumbline.interfaces.pipeline import Pipeline, open_pipeline

from . import mutations as m

DOCSTRING = "plumb-docstring"

INJECTED = (
    "code_default", "code_param_type", "code_return_type", "code_param_renamed",
    "docs_default", "docs_param_type", "docs_return_type", "docs_param_invented", "docs_deprecated",
)  # fmt: skip
CONTROLS = (
    "comment_added", "statement_added", "function_added", "summary_reworded",
    "undocumented_default_changed", "undocumented_type_changed",
)  # fmt: skip
BY_DESIGN = ("raise_removed",)


@dataclass(frozen=True, slots=True)
class Candidate:
    """A corroborated docstring claim: the docs and the code agree on this fact right now."""

    fact_key: str
    symbol_key: str
    aspect: str
    path: str
    qualname: str
    value: str


@dataclass(slots=True)
class Injection:
    """One edit, with the answer known in advance."""

    category: str
    path: str
    qualname: str
    description: str
    edit: Callable[[str], str | None]
    expect_fact: str | None = None
    expect_code: str | None = None
    expect_docs: str | None = None

    @property
    def kind(self) -> str:
        """``inject`` (must be found), ``control`` (must stay silent) or ``by_design``."""
        if self.category in INJECTED:
            return "inject"
        return "control" if self.category in CONTROLS else "by_design"


@dataclass(slots=True)
class Outcome:
    """What happened to one injection."""

    category: str
    kind: str
    description: str
    path: str
    verdict: (
        str  # found | found_wrong_values | missed | clean | false_positive | silent | surprising
    )
    expected_fact: str | None
    new_findings: list[str] = field(default_factory=list)
    extra_findings: list[str] = field(default_factory=list)
    seconds: float = 0.0


def _other_literal(canonical_value: str) -> str | None:
    """A literal that differs from ``canonical_value`` (or ``None`` if it can't be changed)."""
    try:
        value = ast.literal_eval(canonical_value)
    except (ValueError, SyntaxError):
        return None
    if isinstance(value, bool):
        return repr(not value)
    if isinstance(value, int):
        return repr(value + 7)
    if isinstance(value, float):
        return repr(value + 1.5)
    if isinstance(value, str):
        return repr(value + "_x")
    return "0" if value is None else None


def _other_type(canonical_type: str) -> str:
    return "int" if canonical_type == "str" else "str"


def discover(pipeline: Pipeline) -> tuple[list[Candidate], set[str]]:
    """Corroborated docstring claims, and the keys of every fact that has a docstring claim."""
    kb = pipeline.kb
    candidates: list[Candidate] = []
    claimed: set[str] = set()
    for entity in kb._kb.query("Fact").all():
        fact_key = entity.natural_key
        if fact_key is None:
            continue
        claims = kb.claims_on(fact_key)
        docs = [c for c in claims if c.author == DOCSTRING]
        if not docs:
            continue
        claimed.add(fact_key)
        projection = [c for c in claims if c.author == PROJECTOR_PRINCIPAL]
        if not projection or {d.value for d in docs} != {projection[0].value}:
            continue
        symbol_key, _, aspect = fact_key.partition("#")
        module = module_name(docs[0].path)
        if module is None or not symbol_key.removeprefix("py:").startswith(module + "."):
            continue
        candidates.append(
            Candidate(
                fact_key, symbol_key, aspect, docs[0].path,
                symbol_key.removeprefix("py:")[len(module) + 1 :], docs[0].value,
            )
        )  # fmt: skip
    return sorted(candidates, key=lambda c: c.fact_key), claimed


def _docstring_edit(
    transform: Callable[[str, str], str | None],
) -> Callable[[str, str], str | None]:
    """Lift a ``(value, indent) -> value`` docstring transform to a ``(source, qualname) edit."""

    def edit(source: str, qualname: str) -> str | None:
        site = m.docstring_site(source, qualname)
        if site is None:
            return None
        new_value = transform(site.value, site.indent)
        return None if new_value is None else m.replace_docstring(source, qualname, new_value)

    return edit


def _drift(
    c: Candidate, category: str, what: str, edit: Callable[[str], str | None],
    code: str | None, docs: str | None, fact: str | None = None,
) -> Injection:  # fmt: skip
    return Injection(
        category, c.path, c.qualname, f"{c.path}::{c.qualname}: {what}", edit,
        expect_fact=fact or c.fact_key, expect_code=code, expect_docs=docs,
    )  # fmt: skip


def build(category: str, c: Candidate, claimed: set[str], counter: int) -> Injection | None:
    """The injection of ``category`` for candidate ``c``, or ``None`` if it doesn't apply."""
    parts = c.aspect.split(".")
    param = parts[1] if c.aspect.startswith("param.") and len(parts) == 3 else None
    qual = c.qualname

    if category in ("code_default", "docs_default") and param and c.aspect.endswith(".default"):
        new = _other_literal(c.value)
        shown = None if new is None else canonical.canonical_literal(new)
        if new is None or shown is None:
            return None
        if category == "code_default":
            return _drift(
                c, category, f"default of `{param}` {c.value} -> {new}",
                lambda s: m.set_default(s, qual, param, new), code=shown, docs=c.value,
            )  # fmt: skip
        doc_edit = _docstring_edit(lambda v, _i: m.docstring_set_default(v, param, new))
        return _drift(
            c, category, f"docstring default of `{param}` {c.value} -> {new}",
            lambda s: doc_edit(s, qual), code=c.value, docs=shown,
        )  # fmt: skip
    if category in ("code_param_type", "docs_param_type") and param and c.aspect.endswith(".type"):
        other = _other_type(c.value)
        if category == "code_param_type":
            return _drift(
                c, category, f"annotation of `{param}` {c.value} -> {other}",
                lambda s: m.set_param_annotation(s, qual, param, other), code=other, docs=c.value,
            )  # fmt: skip
        doc_edit = _docstring_edit(lambda v, _i: m.docstring_set_param_type(v, param, other))
        return _drift(
            c, category, f"docstring type of `{param}` {c.value} -> {other}",
            lambda s: doc_edit(s, qual), code=c.value, docs=other,
        )  # fmt: skip
    if category in ("code_return_type", "docs_return_type") and c.aspect == "returns.type":
        other = _other_type(c.value)
        if category == "code_return_type":
            return _drift(
                c, category, f"return annotation {c.value} -> {other}",
                lambda s: m.set_return_annotation(s, qual, other), code=other, docs=c.value,
            )  # fmt: skip
        doc_edit = _docstring_edit(lambda v, _i: m.docstring_set_return_type(v, other))
        return _drift(
            c, category, f"docstring return type {c.value} -> {other}",
            lambda s: doc_edit(s, qual), code=c.value, docs=other,
        )  # fmt: skip
    if category == "code_param_renamed" and param and c.aspect.endswith(".exists"):
        return _drift(
            c, category, f"parameter `{param}` renamed in the signature",
            lambda s: _guard_kwargs(s, qual, lambda: m.rename_param(s, qual, param, f"{param}_r")),
            code="false", docs="true",
        )  # fmt: skip
    if category == "docs_param_invented" and c.aspect.endswith(".exists"):
        ghost = f"seeded_ghost_{counter}"
        doc_edit = _docstring_edit(lambda v, _i: m.docstring_add_param(v, ghost, "int"))
        return _drift(
            c, category, f"docstring documents `{ghost}`, which does not exist",
            lambda s: _guard_kwargs(s, qual, lambda: doc_edit(s, qual)),
            code="false", docs="true", fact=f"{c.symbol_key}#param.{ghost}.exists",
        )  # fmt: skip
    if category == "docs_deprecated" and c.aspect.endswith(".exists"):
        doc_edit = _docstring_edit(lambda v, indent: m.docstring_add_deprecated(v, indent))
        return _drift(
            c, category, "docstring declares it deprecated; the code does not",
            lambda s: doc_edit(s, qual), code="false", docs="true",
            fact=f"{c.symbol_key}#deprecated",
        )  # fmt: skip
    return _control(category, c, claimed, counter)


def _control(category: str, c: Candidate, claimed: set[str], counter: int) -> Injection | None:
    """Edits that must not be reported (and the by-design blind spot)."""
    qual, where = c.qualname, f"{c.path}::{c.qualname}"

    def plain(what: str, edit: Callable[[str], str | None], name: str = "") -> Injection:
        return Injection(category, c.path, name or qual, f"{where}: {what}", edit)

    if category == "comment_added":
        return plain("a comment added", lambda s: m.insert_after_docstring(s, qual, "# seeded"))
    if category == "statement_added":
        return plain("a harmless statement added",
                     lambda s: m.insert_after_docstring(s, qual, "_seeded = 0"))  # fmt: skip
    if category == "function_added":
        return plain("a new undocumented function",
                     lambda s: m.append_function(s, f"seeded_extra_{counter}"),
                     name=f"<new {c.path}>")  # fmt: skip
    if category == "summary_reworded":
        doc_edit = _docstring_edit(lambda v, _i: m.docstring_edit_summary(v))
        return plain("summary line reworded", lambda s: doc_edit(s, qual))
    if category == "raise_removed" and c.aspect.startswith("raises."):
        exc = c.aspect.removeprefix("raises.")
        return plain(f"the `raise {exc}` removed (docstring still lists it)",
                     lambda s: m.replace_raise_with_pass(s, qual, exc))  # fmt: skip
    if category in ("undocumented_default_changed", "undocumented_type_changed"):
        return plain(category.replace("_", " "), _undocumented(category, c, claimed))
    return None


def _undocumented(category: str, c: Candidate, claimed: set[str]) -> Callable[[str], str | None]:
    """An edit to a default or type the docstring says nothing about: not drift."""
    default_kind = category == "undocumented_default_changed"

    def edit(source: str) -> str | None:
        tree = _parse(source)
        func = None if tree is None else m.find_function(tree, c.qualname)
        if func is None:
            return None
        params = [*func.args.posonlyargs, *func.args.args, *func.args.kwonlyargs]
        for arg in params:
            if f"{c.symbol_key}#param.{arg.arg}.{'default' if default_kind else 'type'}" in claimed:
                continue
            if default_kind:
                default = _default_of(func, arg.arg)
                other = None if default is None else _other_literal(repr_of(default))
                if other is not None:
                    return m.set_default(source, c.qualname, arg.arg, other)
            elif arg.annotation is not None:
                other_type = _other_type(ast.unparse(arg.annotation))
                return m.set_param_annotation(source, c.qualname, arg.arg, other_type)
        return None

    return edit


def repr_of(node: ast.expr) -> str:
    """The canonical (``repr``) form of a literal expression, or ``""`` if it isn't one."""
    try:
        return repr(ast.literal_eval(node))
    except (ValueError, SyntaxError):
        return ""


def _default_of(func: m.FunctionNode, name: str) -> ast.expr | None:
    positional = [*func.args.posonlyargs, *func.args.args]
    for arg, default in zip(reversed(positional), reversed(func.args.defaults), strict=False):
        if arg.arg == name:
            return default
    for arg, kw_default in zip(func.args.kwonlyargs, func.args.kw_defaults, strict=True):
        if arg.arg == name:
            return kw_default
    return None


def _parse(source: str) -> ast.Module | None:
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def _guard_kwargs(source: str, qualname: str, make: Callable[[], str | None]) -> str | None:
    """Run ``make`` only if no ``**kwargs`` could absorb a parameter that "went missing"."""
    tree = _parse(source)
    func = None if tree is None else m.find_function(tree, qualname)
    return None if func is None or m.has_var_keyword(func) else make()


# --- the run ---------------------------------------------------------------------------


def _git(repo: Path, *args: str, when: str | None = None) -> str:
    who = {"NAME": "Seeded", "EMAIL": "seeded@example.invalid"}
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    for role in ("AUTHOR", "COMMITTER"):
        env |= {f"GIT_{role}_{key}": value for key, value in who.items()}
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
    done = subprocess.run(  # nosec B603 B607 -- fixed argv, local scratch clone
        ["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=True
    )
    return done.stdout.strip()


def judge(inj: Injection, new: list[DriftItem]) -> Outcome:
    """Compare what newly opened with what the injection should have caused."""
    keys = [i.fact_key for i in new]
    out = Outcome(inj.category, inj.kind, inj.description, inj.path, "", inj.expect_fact, keys)
    if inj.kind == "inject":
        hit = next((i for i in new if i.fact_key == inj.expect_fact), None)
        out.extra_findings = [k for k in keys if k != inj.expect_fact]
        if hit is None:
            out.verdict = "missed"
        else:
            docs = {c.value for c in hit.claims if c.author != PROJECTOR_PRINCIPAL}
            ok = hit.code_value == inj.expect_code and inj.expect_docs in docs
            out.verdict = "found" if ok else "found_wrong_values"
    elif inj.kind == "control":
        out.extra_findings = keys
        out.verdict = "clean" if not keys else "false_positive"
    else:
        out.extra_findings = keys
        out.verdict = "silent" if not keys else "surprising"
    return out


class NothingInjected(RuntimeError):
    """No drift was injected at all, so there is nothing to measure.

    Reporting "0 missed" here would read as success. It must fail instead.
    """


@dataclass(slots=True)
class Report:
    """The whole measurement."""

    repo: str
    seed: int
    baseline_commits: int
    baseline_findings: int
    candidates: dict[str, int]
    skipped: dict[str, int]
    requested: dict[str, int]
    outcomes: list[Outcome]

    def table(self) -> dict[str, dict[str, int]]:
        """Counts of each verdict, by category."""
        rows: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for o in self.outcomes:
            rows[o.category][o.verdict] += 1
        return {k: dict(v) for k, v in rows.items()}

    def shortfalls(self) -> dict[str, tuple[int, int]]:
        """Categories that executed fewer injections than requested: ``{name: (done, wanted)}``."""
        done: dict[str, int] = defaultdict(int)
        for o in self.outcomes:
            done[o.category] += 1
        return {c: (done[c], wanted) for c, wanted in self.requested.items() if done[c] < wanted}

    def recall(self) -> tuple[int, int]:
        """``(found, injected)`` over every injection that was made."""
        injected = [o for o in self.outcomes if o.kind == "inject"]
        return sum(o.verdict == "found" for o in injected), len(injected)

    def false_positives(self) -> tuple[int, int]:
        """Controls that produced a finding, out of all controls."""
        controls = [o for o in self.outcomes if o.kind == "control"]
        return sum(o.verdict == "false_positive" for o in controls), len(controls)

    def extras_on_injections(self) -> int:
        """Findings an injection caused beyond the one it should have."""
        return sum(len(o.extra_findings) for o in self.outcomes if o.kind == "inject")


def run(
    source_repo: Path,
    workdir: Path,
    *,
    per_category: int = 10,
    seed: int = 1,
    categories: tuple[str, ...] = (*INJECTED, *CONTROLS, *BY_DESIGN),
    log: Callable[[str], None] = lambda _: None,
) -> Report:
    """Measure ``source_repo``: inject, ingest, judge. ``source_repo`` itself is never modified."""
    workdir.mkdir(parents=True, exist_ok=True)
    clone = workdir / "clone"
    if clone.exists():
        shutil.rmtree(clone)
    subprocess.run(  # nosec B603 B607 -- fixed argv
        ["git", "clone", "--quiet", "--no-hardlinks", str(source_repo), str(clone)], check=True
    )
    kb_path = workdir / "seeded.db"
    kb_path.unlink(missing_ok=True)
    pipeline = open_pipeline(clone, kb_path)

    log("ingesting the baseline history...")
    totals = pipeline.backfill.run()
    baseline = {i.fact_key for i in pipeline.kb.open_drift()}
    log(f"baseline: {totals.commits} commits, {len(baseline)} open contradiction(s)")

    candidates, claimed = discover(pipeline)
    rng = random.Random(seed)
    queues: dict[str, list[Candidate]] = {}
    for category in categories:
        pool = list(candidates)
        rng.shuffle(pool)
        queues[category] = pool
    counts = {cat: len(q) for cat, q in queues.items()}

    used: set[tuple[str, str]] = set()
    outcomes: list[Outcome] = []
    skipped: dict[str, int] = defaultdict(int)
    head = _git(clone, "rev-parse", "HEAD")
    clock = pipeline.reader.describe(head).committed_at
    serial = 0

    plan: list[str] = []
    for group in (INJECTED, CONTROLS, BY_DESIGN):  # injections first: they must not be starved
        wanted = [c for c in categories if c in group]
        for _ in range(per_category):
            round_ = list(wanted)
            rng.shuffle(round_)
            plan.extend(round_)
    requested = dict.fromkeys(categories, per_category)

    for category in plan:
        injection: Injection | None = None
        new_source: str | None = None
        while queues[category] and injection is None:
            cand = queues[category].pop()
            serial += 1
            unit = (
                cand.path,
                cand.qualname if category != "function_added" else f"<new>{cand.path}",
            )
            if unit in used:
                continue
            attempt = build(category, cand, claimed, serial)
            if attempt is None:
                skipped[category] += 1
                continue
            text = (clone / attempt.path).read_bytes().decode("utf-8")  # bytes: keep line endings
            new_source = attempt.edit(text)
            if new_source is None:
                skipped[category] += 1
                continue
            injection, used = attempt, used | {unit}
        if injection is None or new_source is None:
            continue
        (clone / injection.path).write_bytes(new_source.encode("utf-8"))
        _git(clone, "add", "-A")
        clock = clock.replace(microsecond=0) + timedelta(hours=1)
        _git(clone, "-c", f"core.hooksPath={os.devnull}", "commit", "-q", "--no-verify", "-m",
             f"seeded: {injection.category}", when=clock.isoformat())  # fmt: skip

        before = {i.fact_key for i in pipeline.kb.open_drift()}
        started = time.monotonic()
        pipeline.backfill.ingest.run(pipeline.reader.describe(_git(clone, "rev-parse", "HEAD")))
        after = pipeline.kb.open_drift()
        outcome = judge(injection, [i for i in after if i.fact_key not in before])
        outcome.seconds = round(time.monotonic() - started, 3)
        outcomes.append(outcome)
        log(f"{outcome.verdict:<18} {injection.category:<28} {injection.description[:90]}")

    pipeline.kb.close()
    report = Report(
        str(source_repo),
        seed,
        totals.commits,
        len(baseline),
        counts,
        dict(skipped),
        requested,
        outcomes,
    )
    if not any(o.kind == "inject" for o in outcomes):
        raise NothingInjected(report.shortfalls())
    return report


def format_report(report: Report) -> str:
    """The result as a table a person can read."""
    baseline = f"{report.baseline_commits} commits, {report.baseline_findings} open contradictions"
    lines = [
        f"Seeded-drift measurement of {report.repo} (seed {report.seed})",
        f"baseline: {baseline}\n",
    ]
    verdicts = (
        "found",
        "found_wrong_values",
        "missed",
        "clean",
        "false_positive",
        "silent",
        "surprising",
    )
    lines.append(f"{'category':<30}{'n':>4}  " + "  ".join(f"{v[:9]:>9}" for v in verdicts))
    table = report.table()
    for category in (*INJECTED, *CONTROLS, *BY_DESIGN):
        if category in table:
            row = table[category]
            lines.append(
                f"{category:<30}{sum(row.values()):>4}  "
                + "  ".join(f"{row.get(v, 0):>9}" for v in verdicts)
            )
    found, injected = report.recall()
    fp, controls = report.false_positives()
    lines += [
        "",
        f"RECALL on injected drift      {found}/{injected}"
        + (f" = {found / injected:.0%}" if injected else ""),
        f"FALSE POSITIVES on controls   {fp}/{controls}",
        f"EXTRA findings on injections  {report.extras_on_injections()}",
    ]
    short = report.shortfalls()
    if short:
        lines.append("\nSHORTFALL (fewer executed than requested; not enough eligible code):")
        lines += [f"    {name}: {done} of {wanted}" for name, (done, wanted) in short.items()]
    for outcome in report.outcomes:
        if (
            outcome.verdict in ("missed", "found_wrong_values", "false_positive", "surprising")
            or outcome.extra_findings
        ):
            lines.append(f"\n[{outcome.verdict}] {outcome.description}")
            if outcome.expected_fact:
                lines.append(f"    expected: {outcome.expected_fact}")
            for key in outcome.new_findings:
                lines.append(f"    opened:   {key}")
    return "\n".join(lines)


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--repo", type=Path, required=True, help="repository to measure (only read)"
    )
    parser.add_argument("--per-category", type=int, default=10)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--workdir", type=Path, default=Path("seeded-drift-work"))
    parser.add_argument("--report", type=Path, help="also write the full result as JSON")
    args = parser.parse_args()
    report = run(args.repo, args.workdir, per_category=args.per_category, seed=args.seed, log=print)
    print("\n" + format_report(report))
    if args.report:
        args.report.write_text(
            json.dumps(asdict(report), indent=2, default=str) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
