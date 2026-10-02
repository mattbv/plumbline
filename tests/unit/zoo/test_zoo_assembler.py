"""The importer -> assembler path, measured against the zoo's L1 labels (ADR-0004).

Every zoo scenario commit must assemble cleanly, the assembled L1 fields must
stand for exactly what the importer found, and each labeled L1 supersession must
change the *right* field -- and nothing else.
"""

from __future__ import annotations

import pytest

from plumbline.application.symbol_facts import SymbolFields, aspects_of, assemble
from tests.zoo.importing import claims_at
from tests.zoo.model import Layer, Scenario
from tests.zoo.scenarios import ALL

_COMMITS = [(s, c.label) for s in ALL for c in s.commits]


def _fields(scenario: Scenario, label: str) -> dict[str, SymbolFields]:
    return assemble(claims_at(scenario, label))


@pytest.mark.parametrize(
    ("scenario", "label"), _COMMITS, ids=[f"{s.id}@{lb}" for s, lb in _COMMITS]
)
def test_every_snapshot_assembles_and_round_trips(scenario: Scenario, label: str) -> None:
    claims = claims_at(scenario, label)
    fields = assemble(claims)
    for symbol, record in fields.items():
        original = sorted(
            (c.aspect, c.raw_value) for c in claims if c.symbol_key == symbol and c.aspect != "kind"
        )
        assert aspects_of(record) == original, symbol


def _field_for(aspect: str) -> str:
    if aspect == "deprecated":
        return "is_deprecated"
    return "signature_json"


def _l1_cases() -> list[tuple[Scenario, str, str, str, str]]:
    """Labeled supersessions of aspects that live in a Symbol field the importer writes.

    Presence going away (``exists`` / ``param.<p>.exists`` true -> false) is not
    extracted at all: the snapshot-vs-KB diff derives it, so it is skipped here.
    """
    cases = []
    for s in ALL:
        for e in s.expectations:
            if e.layer is not Layer.L1 or not e.symbol.startswith("py:"):
                continue
            if e.aspect == "exists" or e.aspect.endswith(".exists"):
                continue
            cases.append((s, e.commit, e.symbol, e.aspect, _field_for(e.aspect)))
    return cases


@pytest.mark.parametrize(
    ("scenario", "label", "symbol", "aspect", "field"),
    _l1_cases(),
    ids=[f"{s.id}@{lb}:{a}" for s, lb, _, a, _ in _l1_cases()],
)
def test_a_labeled_supersession_changes_exactly_the_responsible_field(
    scenario: Scenario, label: str, symbol: str, aspect: str, field: str
) -> None:
    previous = scenario.commits[scenario.commit_index(label) - 1].label
    before = _fields(scenario, previous)[symbol].as_mapping()
    after = _fields(scenario, label)[symbol].as_mapping()
    changed = {name for name in after if before.get(name) != after[name]}
    assert changed == {field}


def test_the_zoo_has_supersessions_for_both_fields() -> None:
    assert {c[4] for c in _l1_cases()} == {"signature_json", "is_deprecated"}


def test_a_default_change_leaves_every_other_field_alone() -> None:
    scenario = next(s for s in ALL if s.id == "sig_change_docs_stale")
    symbol = "py:sig_change_docs_stale.client.connect"
    before = _fields(scenario, "c1")[symbol]
    after = _fields(scenario, "c2")[symbol]
    assert before.signature_json != after.signature_json
    assert (before.kind, before.present, before.defined_at, before.is_deprecated) == (
        after.kind,
        after.present,
        after.defined_at,
        after.is_deprecated,
    )
