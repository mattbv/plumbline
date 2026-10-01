"""The code importer, measured against the drift zoo's labeled code values.

This is the first time the zoo's labels become real pass/fail checks: wherever
a scenario labels a code value in an aspect the importer is responsible for,
the importer must produce exactly that value -- and where the zoo says the
projector must *abstain*, the importer must emit nothing for the slot.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from plumbline.adapters.python_code_importer import PythonCodeImporter
from plumbline.application.ports import CommitRef
from tests.zoo.model import Expectation, Outcome, Scenario
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
    files = {
        f"scenarios/{scenario.id}/{path}": text.encode()
        for path, text in scenario.files_at(label).items()
    }
    commit = CommitRef("abcdef0" * 5 + "abcde", datetime(2024, 1, 1, tzinfo=UTC), ())
    claims = PythonCodeImporter("zoo", "zoo").extract(files, commit)
    return {(c.symbol_key, c.aspect): c.raw_value for c in claims}


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

    if exp.outcome is Outcome.ABSTAIN:
        assert slot not in projected, "the zoo says the projector must abstain here"
        return
    if exp.outcome is Outcome.UNDOCUMENTED:
        return  # 'nothing to compare' is decided downstream of extraction
    if exp.code_value is not None and not _derived_absence(exp, exp.code_value):
        assert projected.get(slot) == exp.code_value

    if exp.previous_code_value is not None and not _derived_absence(exp, exp.previous_code_value):
        earlier = scenario.commits[scenario.commit_index(exp.commit) - 1].label
        assert _project(scenario, earlier).get(slot) == exp.previous_code_value


def test_the_zoo_actually_exercises_the_importer() -> None:
    """Guard against the parametrization silently collapsing to nothing."""
    assert len(_cases()) >= 25
