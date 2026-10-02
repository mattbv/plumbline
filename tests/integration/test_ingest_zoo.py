"""Ingest the whole drift zoo, commit by commit, into a real Ontolith KB.

No fakes below the use case: the real code importer, the real assembler, the
real `OntolithKnowledgeBase`, a replay clock, and a deterministic ID provider.
This is the first half of M0's exit criterion made executable -- ingesting the
zoo is deterministic across runs -- plus the L1 semantics of PRD §7.1: a changed
code value supersedes (window closed, successor linked), and an unchanged one
writes nothing.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from ontolith.core.ids import SequentialIdProvider

from plumbline.adapters.ontolith_kb import OntolithKnowledgeBase, OutOfOrderIngest
from plumbline.adapters.python_code_importer import PythonCodeImporter
from plumbline.application.symbol_facts import assemble
from plumbline.application.use_cases.ingest import IngestOneCommit
from tests.zoo.builder import timeline
from tests.zoo.importing import ZooHistory, claims_at
from tests.zoo.scenarios import ALL

pytestmark = pytest.mark.integration

HISTORY = ZooHistory(ALL)
TIMES = timeline(ALL)


def _new_kb(path: Path) -> OntolithKnowledgeBase:
    return OntolithKnowledgeBase.initialize(
        path,
        admin_principal_id="admin@zoo.invalid",
        replay=True,
        id_provider=SequentialIdProvider(prefix="id"),
    )


def _ingest(kb: OntolithKnowledgeBase, steps: int | None = None) -> None:
    use_case = IngestOneCommit(
        repo=HISTORY,
        code_importer=PythonCodeImporter("zoo", "zoo"),
        doc_importers=(),
        kb=kb,
    )
    for step in HISTORY.steps[:steps]:
        use_case.run(step.ref)


def _snapshot(kb: OntolithKnowledgeBase) -> list[tuple[object, ...]]:
    """Every assertion, with its subject's natural key, in a stable order."""
    ontology = kb._kb
    rows = []
    for a in ontology.assertions(status=None):
        entity = ontology.get_entity(a.subject)
        rows.append(
            (
                entity.natural_key if entity else a.subject,
                a.predicate,
                a.value,
                str(a.status),
                a.valid_from,
                a.valid_to,
                a.asserted_at,
                a.source,
                a.id,
                a.supersedes,
            )
        )
    return sorted(rows, key=repr)


@pytest.fixture(scope="module")
def zoo_kb(tmp_path_factory: pytest.TempPathFactory) -> OntolithKnowledgeBase:
    started = time.monotonic()
    kb = _new_kb(tmp_path_factory.mktemp("zoo") / "kb.db")
    _ingest(kb)
    print(f"ingested {len(HISTORY.steps)} commits in {time.monotonic() - started:.1f}s")
    return kb


def _history(kb: OntolithKnowledgeBase, symbol: str, field: str) -> list[object]:
    ontology = kb._kb
    entity = ontology.backend.get_entity_by_natural_key("default", "Symbol", symbol)
    assert entity is not None, symbol
    found = ontology.assertions(subject=entity.id, predicate=f"Symbol.{field}", status=None)
    return sorted(found, key=lambda a: a.valid_from)  # type: ignore[no-any-return]


class TestFinalState:
    def test_the_kb_holds_exactly_what_the_last_snapshot_assembles_to(
        self, zoo_kb: OntolithKnowledgeBase
    ) -> None:
        checked = 0
        for scenario in ALL:
            last = scenario.commits[-1].label
            for symbol, fields in assemble(claims_at(scenario, last)).items():
                assert zoo_kb.symbol_fields(symbol) == fields.as_mapping(), symbol
                checked += 1
        assert checked > 50  # guard against the loop silently covering nothing

    def test_an_unknown_symbol_is_none(self, zoo_kb: OntolithKnowledgeBase) -> None:
        assert zoo_kb.symbol_fields("py:nobody.home") is None


class TestSupersession:
    SYMBOL = "py:sig_change_docs_stale.client.connect"

    def test_a_changed_default_closes_the_old_window_and_links_the_successor(
        self, zoo_kb: OntolithKnowledgeBase
    ) -> None:
        old, new = _history(zoo_kb, self.SYMBOL, "signature_json")  # type: ignore[misc]
        c1 = TIMES[("sig_change_docs_stale", "c1")]
        c2 = TIMES[("sig_change_docs_stale", "c2")]

        assert str(old.status) == "superseded" and str(new.status) == "active"
        assert (old.valid_from, old.valid_to) == (c1, c2)
        assert (new.valid_from, new.valid_to) == (c2, None)
        assert new.supersedes == old.id
        assert '"default":"30"' in old.value and '"default":"60"' in new.value

    def test_the_replay_clock_pins_assertion_time_to_the_commit(
        self, zoo_kb: OntolithKnowledgeBase
    ) -> None:
        """So `as_of(c1)` can see the old signature (PRD §7.7)."""
        old, new = _history(zoo_kb, self.SYMBOL, "signature_json")  # type: ignore[misc]
        assert old.asserted_at == TIMES[("sig_change_docs_stale", "c1")]
        assert new.asserted_at == TIMES[("sig_change_docs_stale", "c2")]

    def test_provenance_points_at_the_definition_at_that_commit(
        self, zoo_kb: OntolithKnowledgeBase
    ) -> None:
        old, new = _history(zoo_kb, self.SYMBOL, "signature_json")  # type: ignore[misc]
        shas = {
            step.label: step.ref.sha
            for step in HISTORY.steps
            if step.scenario.id == "sig_change_docs_stale"
        }
        assert f"@{shas['c1']}/" in old.source and f"@{shas['c2']}/" in new.source
        assert new.source.endswith("src/sig_change_docs_stale/client.py#L1-L2")

    def test_a_change_to_one_field_does_not_touch_the_others(
        self, zoo_kb: OntolithKnowledgeBase
    ) -> None:
        for field in ("kind", "present", "defined_at", "is_deprecated"):
            assert len(_history(zoo_kb, self.SYMBOL, field)) == 1, field

    def test_only_the_deprecation_flag_moves_when_only_that_changes(
        self, zoo_kb: OntolithKnowledgeBase
    ) -> None:
        symbol = "py:deprecation_code_ahead.api.old"
        assert [a.value for a in _history(zoo_kb, symbol, "is_deprecated")] == ["false", "true"]
        assert len(_history(zoo_kb, symbol, "signature_json")) == 1

    def test_unrelated_commits_write_nothing(self, zoo_kb: OntolithKnowledgeBase) -> None:
        """drift_persists c3 edits only NOTES.md: no Python file, no new assertions."""
        symbol = "py:drift_persists.client.connect"
        assert len(_history(zoo_kb, symbol, "signature_json")) == 2  # c1 -> c2 only


class TestIdempotenceAndDeterminism:
    def test_re_ingesting_the_latest_commit_of_each_scenario_changes_nothing(
        self, tmp_path: Path
    ) -> None:
        """ING-7: delivering the same commit twice is a no-op."""
        kb = _new_kb(tmp_path / "kb.db")
        _ingest(kb)
        before = _snapshot(kb)
        use_case = IngestOneCommit(
            repo=HISTORY,
            code_importer=PythonCodeImporter("zoo", "zoo"),
            doc_importers=(),
            kb=kb,
        )
        latest = {step.scenario.id: step for step in HISTORY.steps}
        for step in latest.values():
            use_case.run(step.ref)
        assert _snapshot(kb) == before

    def test_applying_an_older_commit_over_newer_state_is_refused(self, tmp_path: Path) -> None:
        """Replaying history onto a KB that is ahead would move it backwards."""
        kb = _new_kb(tmp_path / "kb.db")
        _ingest(kb)
        before = _snapshot(kb)
        first = next(s for s in HISTORY.steps if s.scenario.id == "sig_change_docs_stale")
        use_case = IngestOneCommit(
            repo=HISTORY,
            code_importer=PythonCodeImporter("zoo", "zoo"),
            doc_importers=(),
            kb=kb,
        )
        with pytest.raises(OutOfOrderIngest, match="before the current value"):
            use_case.run(first.ref)
        assert _snapshot(kb) == before

    def test_two_ingestions_produce_identical_kb_snapshots(
        self, zoo_kb: OntolithKnowledgeBase, tmp_path: Path
    ) -> None:
        second = _new_kb(tmp_path / "second.db")
        _ingest(second)
        first_rows = _snapshot(zoo_kb)
        assert len(first_rows) > 300
        assert _snapshot(second) == first_rows


class TestLiveMode:
    """Outside backfill the clock is real: valid time is still the commit's (PRD §7.7)."""

    def test_valid_time_is_the_commit_time_but_assertion_time_is_ingest_time(
        self, tmp_path: Path
    ) -> None:
        kb = OntolithKnowledgeBase.initialize(
            tmp_path / "live.db", admin_principal_id="admin@zoo.invalid", replay=False
        )
        history = ZooHistory([next(s for s in ALL if s.id == "sig_change_docs_stale")])
        use_case = IngestOneCommit(
            repo=history,
            code_importer=PythonCodeImporter("zoo", "zoo"),
            doc_importers=(),
            kb=kb,
        )
        for step in history.steps:
            use_case.run(step.ref)

        symbol = "py:sig_change_docs_stale.client.connect"
        old, new = _history(kb, symbol, "signature_json")  # type: ignore[misc]
        c1 = history.steps[0].ref.committed_at
        c2 = history.steps[1].ref.committed_at
        assert (old.valid_from, old.valid_to, new.valid_from) == (c1, c2, c2)
        assert old.asserted_at > c2 and new.asserted_at > c2  # real ingest time, not replayed
