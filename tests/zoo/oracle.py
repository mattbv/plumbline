"""A pure oracle and linter for the zoo's labels.

The oracle derives, from the *inputs* of a slot (the code value and the doc
claims), the routing outcome that PRD §7.1 / §7.4 / §7.7 / DRF-3..5 prescribe.
The linter then checks every hand-written label against it. This is not the
Plumbline pipeline -- it is a second, independent statement of the same rules,
so a mislabeled scenario fails here instead of silently corrupting the M1
precision/recall numbers computed against the zoo.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Sequence

from plumbline.domain import aspects, canonical
from plumbline.domain.aspects import Aspect, ValueShape

from .model import (
    DOC_PRINCIPALS,
    ClaimsExpectation,
    ClosureExpectation,
    DriftClass,
    Expectation,
    Layer,
    Outcome,
    Scenario,
    StateExpectation,
)

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_PLACEHOLDERS = {
    "<p>": _IDENT,
    "<f>": r"[A-Za-z0-9_-]+",
    "<cmd>": r"[A-Za-z0-9_-]+",
    "<VAR>": r"[A-Z][A-Z0-9_]*",
    "<Exc>": rf"{_IDENT}(?:\.{_IDENT})*",
}


def _template_regex(name: str) -> re.Pattern[str]:
    pattern = re.escape(name)
    for placeholder, expr in _PLACEHOLDERS.items():
        pattern = pattern.replace(re.escape(placeholder), expr)
    return re.compile(rf"^{pattern}$")


_ASPECT_PATTERNS: tuple[tuple[re.Pattern[str], Aspect], ...] = tuple(
    (_template_regex(a.name), a) for a in aspects.CATALOG
)


def resolve_aspect(concrete: str) -> Aspect | None:
    """Return the catalog entry a concrete aspect name (e.g. ``param.timeout.default``) matches."""
    for pattern, aspect in _ASPECT_PATTERNS:
        if pattern.match(concrete):
            return aspect
    return None


def value_problem(aspect: Aspect, value: str) -> str | None:
    """Return why `value` is not the canonical form for `aspect`, or ``None`` if it is."""
    name = aspect.name
    if aspect.value_shape is ValueShape.BOOLEAN:
        return None if value in ("true", "false") else "boolean must be 'true' or 'false'"
    if aspect.value_shape is ValueShape.VERSION:
        return None if canonical.canonical_version(value) == value else "not a canonical version"
    if name == "param_names":
        try:
            names = json.loads(value)
        except ValueError:
            return "param_names must be a JSON list"
        ok = isinstance(names, list) and all(isinstance(n, str) for n in names)
        return None if ok else "param_names must be a JSON list of strings"
    if name == "param.<p>.default":
        return None if canonical.canonical_literal(value) == value else "not a canonical literal"
    if name in ("param.<p>.type", "returns.type"):
        canon = canonical.canonical_type_annotation(value)
        return None if canon == value else f"not canonical (expected {canon!r})"
    return None if value else "empty value"


def expected_outcome(
    layer: Layer,
    code_value: str | None,
    previous_code_value: str | None,
    claims: Sequence[tuple[str, str]],
) -> Outcome:
    """Derive the routing outcome that the PRD prescribes for these inputs."""
    if layer is Layer.L1:
        # Code history is time_varying: a changed value supersedes (PRD §7.1).
        return Outcome.SUPERSEDE
    if not claims:
        return Outcome.UNDOCUMENTED  # nothing to compare (DRF-5)
    if code_value is None:
        return Outcome.ABSTAIN  # projector abstains; claims stay unverified (DRF-3)
    if any(value != code_value for _, value in claims):
        return Outcome.CONTRADICT  # static slot: any value difference (PRD §7.1)
    return Outcome.CORROBORATE  # same value everywhere: all kept, never merged


def expected_drift_class(code_value: str | None, claims: Sequence[tuple[str, str]]) -> DriftClass:
    """Classify a contradiction by its members (DRF-4; PRD §14 #3 and #4).

    If the doc claims disagree *among themselves* the contradiction is a
    ``doc_vs_doc`` one, and it also involves the code when the projection is
    present. If every doc claim agrees, it is purely doc-vs-code.
    """
    docs_disagree = len({value for _, value in claims}) > 1
    if code_value is None:
        return DriftClass.DOC_VS_DOC
    return DriftClass.DOC_VS_DOC_VS_CODE if docs_disagree else DriftClass.DOC_VS_CODE


def _module_depth(files: dict[str, str], symbol_path: list[str]) -> int:
    """Length of the longest prefix of the dotted path that is a module/package file."""
    for length in range(len(symbol_path), 0, -1):
        base = "src/" + "/".join(symbol_path[:length])
        if f"{base}.py" in files or f"{base}/__init__.py" in files:
            return length
    return 0


def _symbol_problems(scenario: Scenario, where: str, commit: str, symbol: str) -> list[str]:
    """Problems with a symbol key: right scenario, and its module exists at `commit`."""
    if symbol.startswith("py:"):
        path = symbol.removeprefix("py:").split(".")
        if path[0] != scenario.id:
            return [f"{where}: symbol must start with the scenario id"]
        depth = _module_depth(scenario.files_at(commit), path)
        if depth < min(2, len(path) - 1):
            return [f"{where}: no module for this symbol exists at {commit}"]
        return []
    if not symbol.startswith(f"project:{scenario.id}"):
        return [f"{where}: symbol must be 'py:<id>.…' or 'project:<id>'"]
    return []


def _lint_closure(scenario: Scenario, index: int, closure: ClosureExpectation) -> list[str]:
    where = f"{scenario.id} closure #{index} ({closure.symbol} @ {closure.commit})"
    if closure.commit not in [c.label for c in scenario.commits]:
        return [f"{where}: unknown commit {closure.commit!r}"]
    if not closure.symbol.startswith("py:"):
        return [f"{where}: only Python modules and classes have a namespace"]
    return _symbol_problems(scenario, where, closure.commit, closure.symbol)


_STATE_KINDS = frozenset({"module", "class", "function", "method", "attribute", "ambiguous"})


def _module_ever_existed(scenario: Scenario, commit: str, path: list[str]) -> bool:
    """Whether some prefix of the dotted path was a module file at or before `commit`."""
    upto = scenario.commit_index(commit)
    for label in (c.label for c in scenario.commits[: upto + 1]):
        files = scenario.files_at(label)
        for length in range(len(path), 0, -1):
            base = "/".join(path[:length])
            if any(
                f"{root}{base}{tail}" in files
                for root in ("", "src/")
                for tail in (".py", "/__init__.py")
            ):
                return True
    return False


def _lint_state(scenario: Scenario, index: int, state: StateExpectation) -> list[str]:
    where = f"{scenario.id} state #{index} ({state.symbol} @ {state.commit})"
    if state.commit not in [c.label for c in scenario.commits]:
        return [f"{where}: unknown commit {state.commit!r}"]
    if not state.symbol.startswith("py:"):
        return [f"{where}: only Python symbols have stored L1 state here"]
    problems: list[str] = []
    path = state.symbol.removeprefix("py:").split(".")
    if path[0] != scenario.id:
        problems.append(f"{where}: symbol must start with the scenario id")
    elif not _module_ever_existed(scenario, state.commit, path):
        problems.append(f"{where}: no module for this symbol existed by {state.commit}")
    if state.kind is not None and state.kind not in _STATE_KINDS:
        problems.append(f"{where}: unknown kind {state.kind!r}")
    if state.defined_at is not None and not state.present:
        problems.append(f"{where}: defined_at is only meaningful for a present symbol")
    return problems


def _lint_claims(scenario: Scenario, index: int, expected: ClaimsExpectation) -> list[str]:
    where = (
        f"{scenario.id} claims #{index} ({expected.symbol}#{expected.aspect} @ {expected.commit})"
    )
    if expected.commit not in [c.label for c in scenario.commits]:
        return [f"{where}: unknown commit {expected.commit!r}"]
    problems: list[str] = []
    path = expected.symbol.removeprefix("py:").split(".")
    if not expected.symbol.startswith("py:") or path[0] != scenario.id:
        problems.append(f"{where}: symbol must be 'py:<id>.…'")
    elif not _module_ever_existed(scenario, expected.commit, path):
        problems.append(f"{where}: no module for this symbol existed by {expected.commit}")
    aspect = resolve_aspect(expected.aspect)
    if aspect is None:
        problems.append(f"{where}: aspect is not in the catalog")
    else:
        for principal, value in expected.claims:
            if principal not in DOC_PRINCIPALS:
                problems.append(f"{where}: {principal!r} is not a doc-claim importer principal")
            elif why := value_problem(aspect, value):
                problems.append(f"{where}: claim by {principal} {value!r}: {why}")
    return problems


def _lint_expectation(scenario: Scenario, index: int, exp: Expectation) -> list[str]:
    where = f"{scenario.id} expectation #{index} ({exp.symbol}#{exp.aspect} @ {exp.commit})"
    problems: list[str] = []
    labels = [c.label for c in scenario.commits]

    if exp.commit not in labels:
        return [f"{where}: unknown commit {exp.commit!r}"]
    if exp.introduced_in is not None and exp.introduced_in not in labels:
        problems.append(f"{where}: unknown introduced_in {exp.introduced_in!r}")
    elif exp.introduced_in is not None and labels.index(exp.introduced_in) > labels.index(
        exp.commit
    ):
        problems.append(f"{where}: introduced_in is after the commit it is observed at")

    if exp.withheld_value is not None and (
        exp.outcome is not Outcome.ABSTAIN or exp.code_value is not None
    ):
        problems.append(f"{where}: withheld_value belongs on an ABSTAIN with no code_value")

    aspect = resolve_aspect(exp.aspect)
    if aspect is None:
        problems.append(f"{where}: aspect is not in the catalog")
    else:
        for label, value in [
            ("code_value", exp.code_value),
            ("previous_code_value", exp.previous_code_value),
            ("withheld_value", exp.withheld_value),
        ]:
            if value is not None and (why := value_problem(aspect, value)):
                problems.append(f"{where}: {label} {value!r}: {why}")
        for principal, value in exp.claims:
            if why := value_problem(aspect, value):
                problems.append(f"{where}: claim by {principal} {value!r}: {why}")
        if not aspect.drift_capable and exp.outcome is Outcome.CONTRADICT:
            problems.append(f"{where}: {exp.aspect} is corroboration-only and can never contradict")

    problems.extend(_symbol_problems(scenario, where, exp.commit, exp.symbol))

    for principal, _ in exp.claims:
        if principal not in DOC_PRINCIPALS:
            problems.append(f"{where}: {principal!r} is not a doc-claim importer principal")

    if exp.layer is Layer.L1:
        if exp.claims:
            problems.append(f"{where}: L1 expectations carry no doc claims")
        if exp.code_value is None or exp.previous_code_value is None:
            problems.append(f"{where}: L1 supersession needs code_value and previous_code_value")
        elif exp.code_value == exp.previous_code_value:
            problems.append(f"{where}: L1 supersession needs the value to change")
    elif exp.previous_code_value is not None:
        problems.append(f"{where}: previous_code_value is only meaningful on L1")

    derived = expected_outcome(exp.layer, exp.code_value, exp.previous_code_value, exp.claims)
    if exp.outcome is not derived:
        problems.append(f"{where}: labeled {exp.outcome}, but the inputs imply {derived}")

    if exp.outcome is Outcome.CONTRADICT:
        if exp.drift_class is None:
            problems.append(f"{where}: CONTRADICT needs a drift_class")
        else:
            want = expected_drift_class(exp.code_value, exp.claims)
            if exp.drift_class is not want:
                problems.append(f"{where}: drift_class {exp.drift_class}, members imply {want}")
    elif exp.drift_class is not None or exp.disposition is not None:
        problems.append(f"{where}: drift_class/disposition only apply to CONTRADICT")
    return problems


def lint(scenario: Scenario) -> list[str]:
    """Return every problem found in `scenario` (empty means it is well formed)."""
    problems: list[str] = []
    if not (scenario.id.isidentifier() and scenario.id == scenario.id.lower()):
        problems.append(f"{scenario.id}: id must be a lowercase Python identifier")
    if not scenario.commits:
        problems.append(f"{scenario.id}: no commits")
    if not (scenario.expectations or scenario.closures or scenario.states or scenario.claim_states):
        problems.append(f"{scenario.id}: no expectations")
    labels = [c.label for c in scenario.commits]
    if len(labels) != len(set(labels)):
        problems.append(f"{scenario.id}: duplicate commit labels")

    for commit in scenario.commits:
        for path in (*commit.write, *commit.delete):
            if path.startswith("/") or ".." in path.split("/") or "\\" in path:
                problems.append(f"{scenario.id}/{commit.label}: bad path {path!r}")
    if problems:
        return problems

    for commit in scenario.commits:
        for path, text in scenario.files_at(commit.label).items():
            if not path.endswith(".py"):
                continue
            intentionally_broken = path in commit.broken
            try:
                ast.parse(text)
            except SyntaxError as err:
                if not intentionally_broken and path in commit.write:
                    problems.append(f"{scenario.id}@{commit.label}: {path} does not parse: {err}")
            else:
                if intentionally_broken:
                    problems.append(
                        f"{scenario.id}@{commit.label}: {path} is marked broken but parses"
                    )
    for index, exp in enumerate(scenario.expectations):
        problems.extend(_lint_expectation(scenario, index, exp))
    for index, closure in enumerate(scenario.closures):
        problems.extend(_lint_closure(scenario, index, closure))
    for index, state in enumerate(scenario.states):
        problems.extend(_lint_state(scenario, index, state))
    for index, expected in enumerate(scenario.claim_states):
        problems.extend(_lint_claims(scenario, index, expected))
    return problems
