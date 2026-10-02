"""Removal and key ownership, end to end against a real Ontolith KB (ADR-0005).

The zoo is ingested one commit at a time; after each commit the stored state of
every labeled symbol is recorded, so a test can assert what the KB said *at that
moment* -- including that it deliberately did not change.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from ontolith.core.ids import SequentialIdProvider

from plumbline.adapters.docstring_claim_importer import DocstringClaimImporter
from plumbline.adapters.ontolith_kb import OntolithKnowledgeBase
from plumbline.adapters.python_code_importer import PythonCodeImporter
from plumbline.application.symbol_facts import KeyConflict
from plumbline.application.use_cases.ingest import IngestOneCommit, IngestReport
from tests.zoo.builder import timeline
from tests.zoo.importing import ZooHistory
from tests.zoo.model import Layer, Scenario, StateExpectation
from tests.zoo.scenarios import ALL

pytestmark = pytest.mark.integration

HISTORY = ZooHistory(ALL)
TIMES = timeline(ALL)
STATES = [(s, st) for s in ALL for st in s.states]


@dataclass
class Replayed:
    kb: OntolithKnowledgeBase
    reports: dict[tuple[str, str], IngestReport]
    observed: dict[tuple[str, str, str], dict[str, str] | None]


@pytest.fixture(scope="module")
def replayed(tmp_path_factory: pytest.TempPathFactory) -> Replayed:
    kb = OntolithKnowledgeBase.initialize(
        tmp_path_factory.mktemp("removal") / "kb.db",
        admin_principal_id="admin@zoo.invalid",
        replay=True,
        id_provider=SequentialIdProvider(prefix="id"),
    )
    use_case = IngestOneCommit(
        repo=HISTORY,
        code_importer=PythonCodeImporter("zoo", "zoo"),
        doc_importers=(DocstringClaimImporter("zoo", "zoo"),),
        kb=kb,
        repo_slug="zoo/zoo",
    )
    reports: dict[tuple[str, str], IngestReport] = {}
    observed: dict[tuple[str, str, str], dict[str, str] | None] = {}
    for step in HISTORY.steps:
        reports[(step.scenario.id, step.label)] = use_case.run(step.ref)
        for state in step.scenario.states:
            if state.commit == step.label:
                observed[(step.scenario.id, step.label, state.symbol)] = kb.symbol_fields(
                    state.symbol
                )
    return Replayed(kb, reports, observed)


@pytest.mark.parametrize(
    ("scenario", "state"),
    STATES,
    ids=[f"{s.id}@{st.commit}:{st.symbol.split('.', 1)[-1]}" for s, st in STATES],
)
def test_the_kb_stores_what_the_zoo_labels(
    replayed: Replayed, scenario: Scenario, state: StateExpectation
) -> None:
    fields = replayed.observed[(scenario.id, state.commit, state.symbol)]
    assert fields is not None, f"{state.symbol} was never stored"
    assert fields["present"] == ("true" if state.present else "false")
    if state.kind is not None:
        assert fields["kind"] == state.kind
    if state.defined_at is not None:
        assert fields["defined_at"] == f"scenarios/{scenario.id}/{state.defined_at}"


def test_the_zoo_labels_both_removal_and_survival() -> None:
    assert {st.present for _, st in STATES} == {True, False}
    assert len(STATES) >= 30


def _history(kb: OntolithKnowledgeBase, symbol: str, field: str) -> list[object]:
    ontology = kb._kb
    entity = ontology.backend.get_entity_by_natural_key("default", "Symbol", symbol)
    assert entity is not None, symbol
    found = ontology.assertions(subject=entity.id, predicate=f"Symbol.{field}", status=None)
    return sorted(found, key=lambda a: a.valid_from)  # type: ignore[no-any-return]


def _l1_removals() -> list[tuple[Scenario, str, str]]:
    return [
        (s, e.commit, e.symbol)
        for s in ALL
        for e in s.expectations
        if e.layer is Layer.L1
        and e.aspect == "exists"
        and e.symbol.startswith("py:")
        and e.code_value == "false"
    ]


@pytest.mark.parametrize(
    ("scenario", "label", "symbol"),
    _l1_removals(),
    ids=[f"{s.id}@{lb}" for s, lb, _ in _l1_removals()],
)
def test_every_labeled_exists_true_to_false_supersession_is_stored_as_present_flipping(
    replayed: Replayed, scenario: Scenario, label: str, symbol: str
) -> None:
    """The L1 labels the assembler tests could not check before (ADR-0004) now are."""
    was, now = _history(replayed.kb, symbol, "present")[-2:]
    assert (was.value, now.value) == ("true", "false")  # type: ignore[attr-defined]
    assert now.valid_from == TIMES[(scenario.id, label)]  # type: ignore[attr-defined]
    assert was.valid_to == now.valid_from  # type: ignore[attr-defined]


def test_the_zoo_has_labeled_removals() -> None:
    assert len(_l1_removals()) >= 3


class TestReports:
    def test_deleting_a_file_reports_its_symbols_as_removed(self, replayed: Replayed) -> None:
        report = replayed.reports[("file_deleted", "c2")]
        assert set(report.removed) == {
            "py:file_deleted.api",
            "py:file_deleted.api.f",
            "py:file_deleted.api.g",
        }

    def test_a_syntax_error_removes_nothing_and_reports_the_file(self, replayed: Replayed) -> None:
        report = replayed.reports[("syntax_error_edit", "c2")]
        assert report.removed == ()
        assert report.unanalyzed == ("scenarios/syntax_error_edit/src/syntax_error_edit/api.py",)
        assert report.written == 0

    def test_a_rename_removes_old_keys_and_leaves_the_new_ones(self, replayed: Replayed) -> None:
        report = replayed.reports[("file_renamed", "c2")]
        assert set(report.removed) == {"py:file_renamed.old", "py:file_renamed.old.f"}

    def test_a_flat_to_src_move_removes_nothing(self, replayed: Replayed) -> None:
        report = replayed.reports[("layout_move_same_key", "c2")]
        assert report.removed == () and report.conflicts == ()

    def test_an_ambiguous_name_removes_nothing(self, replayed: Replayed) -> None:
        assert replayed.reports[("name_becomes_duplicated", "c2")].removed == ()
        assert replayed.reports[("class_becomes_ambiguous", "c2")].removed == ()

    def test_the_submodule_import_collision_is_reported_not_flipped(
        self, replayed: Replayed
    ) -> None:
        root = "scenarios/submodule_import_collision/src/submodule_import_collision"
        report = replayed.reports[("submodule_import_collision", "c2")]
        assert report.conflicts == (
            KeyConflict(
                "py:submodule_import_collision.sub", f"{root}/sub.py", f"{root}/__init__.py"
            ),
        )

    def test_unrelated_commits_report_nothing(self, replayed: Replayed) -> None:
        report = replayed.reports[("drift_persists", "c3")]
        assert (report.written, report.removed, report.unanalyzed, report.conflicts) == (
            0,
            (),
            (),
            (),
        )


class TestNoFlapping:
    def test_the_modules_kind_and_path_are_written_exactly_once(self, replayed: Replayed) -> None:
        """Three commits touch both files; the key never moves between owners."""
        symbol = "py:submodule_import_collision.sub"
        assert len(_history(replayed.kb, symbol, "kind")) == 1
        assert len(_history(replayed.kb, symbol, "defined_at")) == 1

    def test_the_alias_first_order_takes_over_exactly_once(self, replayed: Replayed) -> None:
        symbol = "py:submodule_import_alias_first.sub"
        kinds = [a.value for a in _history(replayed.kb, symbol, "kind")]  # type: ignore[attr-defined]
        assert kinds == ["attribute", "module"]


def test_a_removed_then_restored_symbol_has_three_present_windows(replayed: Replayed) -> None:
    windows = _history(replayed.kb, "py:symbol_returns.api.f", "present")
    assert [a.value for a in windows] == ["true", "false", "true"]  # type: ignore[attr-defined]


def test_removal_ingestion_is_deterministic(replayed: Replayed, tmp_path: Path) -> None:
    from tests.integration.test_ingest_zoo import _ingest, _new_kb, _snapshot

    second = _new_kb(tmp_path / "again.db")
    _ingest(second)
    # `replayed` used repo_slug and the same ids; compare against a fresh identical ingest.
    again = _new_kb(tmp_path / "third.db")
    _ingest(again)
    assert _snapshot(second) == _snapshot(again)
    assert len(_snapshot(second)) > 500
