"""The code importer, measured against the drift zoo's labeled code values.

This is the first time the zoo's labels become real pass/fail checks: wherever
a scenario labels a code value in an aspect the importer is responsible for,
the importer must produce exactly that value -- and where the zoo says the
projector must *abstain*, the importer must emit nothing for the slot.
"""

from __future__ import annotations

import json

import pytest

from tests.zoo.importing import claims_at
from tests.zoo.model import ClosureExpectation, Expectation, Outcome, Scenario
from tests.zoo.scenarios import ALL

_HANDLED_PREFIXES = ("param.", "raises.")
_HANDLED_EXACT = {"exists", "param_names", "returns.type", "deprecated"}


def _handled(aspect: str) -> bool:
    return aspect in _HANDLED_EXACT or aspect.startswith(_HANDLED_PREFIXES)


def _derived_absence(exp: Expectation, value: str | None) -> bool:
    """'false' for presence-style aspects is a snapshot-vs-KB difference, not an extraction."""
    presence = (
        exp.aspect in ("exists",)
        or exp.aspect.endswith(".exists")
        or exp.aspect.startswith("raises.")
    )
    return value == "false" and presence


def _project(scenario: Scenario, label: str) -> dict[tuple[str, str], str]:
    return {(c.symbol_key, c.aspect): c.raw_value for c in claims_at(scenario, label)}


def _stated_or_derived(projected: dict[tuple[str, str], str], exp: Expectation) -> str | None:
    """The importer's own claim, or what follows from its ``param_names`` for a starred name.

    `param.concepts.exists` is not a claim the importer makes (starred parameters appear only
    in ``param_names``); the projector derives it, so the label is checked the same way.
    """
    stated = projected.get((exp.symbol, exp.aspect))
    if stated is not None or not (
        exp.aspect.startswith("param.") and exp.aspect.endswith(".exists")
    ):
        return stated
    names = json.loads(projected.get((exp.symbol, "param_names"), "[]"))
    bare = exp.aspect.removeprefix("param.").removesuffix(".exists")
    return "true" if bare in {n.lstrip("*") for n in names if n.startswith("*")} else None


def _cases() -> list[tuple[Scenario, Expectation]]:
    return [
        (s, e)
        for s in ALL
        for e in s.expectations
        if e.symbol.startswith("py:") and _handled(e.aspect)
    ]


@pytest.mark.parametrize(
    ("scenario", "exp"),
    _cases(),
    ids=[f"{s.id}-{e.commit}-{e.aspect}-{e.layer}" for s, e in _cases()],
)
def test_importer_matches_the_zoo_labels(scenario: Scenario, exp: Expectation) -> None:
    slot = (exp.symbol, exp.aspect)
    projected = _project(scenario, exp.commit)

    if _derived_absence(exp, exp.code_value):
        # A labeled 'false' is only sound if the importer really never bound the name.
        assert slot not in projected, "the zoo says absent, but the importer found the name"
    if exp.outcome is Outcome.ABSTAIN:
        assert slot not in projected, "the zoo says the projector must abstain here"
        return
    if exp.outcome is Outcome.UNDOCUMENTED:
        return  # 'nothing to compare' is decided downstream of extraction
    if exp.code_value is not None and not _derived_absence(exp, exp.code_value):
        assert _stated_or_derived(projected, exp) == exp.code_value

    if exp.previous_code_value is not None and not _derived_absence(exp, exp.previous_code_value):
        earlier = scenario.commits[scenario.commit_index(exp.commit) - 1].label
        assert _project(scenario, earlier).get(slot) == exp.previous_code_value


def test_the_zoo_actually_exercises_the_importer() -> None:
    """Guard against the parametrization silently collapsing to nothing."""
    assert len(_cases()) >= 25


def _closure_cases() -> list[tuple[Scenario, ClosureExpectation]]:
    return [(s, c) for s in ALL for c in s.closures]


@pytest.mark.parametrize(
    ("scenario", "closure"),
    _closure_cases(),
    ids=[f"{s.id}-{c.symbol.rsplit('.', 1)[-1]}" for s, c in _closure_cases()],
)
def test_importer_matches_the_zoo_closure_labels(
    scenario: Scenario, closure: ClosureExpectation
) -> None:
    projected = _project(scenario, closure.commit)
    expected = "true" if closure.closed else "false"
    assert projected.get((closure.symbol, "namespace_closed")) == expected


def test_closure_labels_cover_both_verdicts_and_both_kinds() -> None:
    labels = _closure_cases()
    assert {c.closed for _, c in labels} == {True, False}
    kinds = {"class" if c.symbol.split(".")[-1][:1].isupper() else "module" for _, c in labels}
    assert kinds == {"class", "module"}
