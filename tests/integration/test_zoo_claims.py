"""Doc claims, end to end against a real Ontolith KB (ADR-0006).

The zoo is ingested one commit at a time with the real code importer *and* the real
docstring importer. After each commit the doc claims the KB holds on every labeled
fact are recorded, so each label is checked at the moment it applies.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from ontolith.core.ids import SequentialIdProvider

from plumbline.adapters.docstring_claim_importer import PRINCIPAL, DocstringClaimImporter
from plumbline.adapters.ontolith_kb import OntolithKnowledgeBase
from plumbline.adapters.python_code_importer import PythonCodeImporter
from plumbline.application.use_cases.ingest import IngestOneCommit, IngestReport
from tests.zoo.builder import timeline
from tests.zoo.importing import ZooHistory
from tests.zoo.model import ClaimsExpectation, Expectation, Layer, Scenario
from tests.zoo.scenarios import ALL

pytestmark = pytest.mark.integration

HISTORY = ZooHistory(ALL)
TIMES = timeline(ALL)
_PRESENT = {"active", "flagged"}


def _docstring_aspect(aspect: str) -> bool:
    return aspect.startswith(("param.", "raises.")) or aspect in ("returns.type", "deprecated")


def _l2_cases() -> list[tuple[Scenario, Expectation]]:
    return [
        (s, e)
        for s in ALL
        for e in s.expectations
        if e.layer is Layer.L2 and e.symbol.startswith("py:") and _docstring_aspect(e.aspect)
    ]


def _claim_cases() -> list[tuple[Scenario, ClaimsExpectation]]:
    return [(s, c) for s in ALL for c in s.claim_states]


def _present_values(kb: OntolithKnowledgeBase, fact_key: str) -> set[str]:
    """Values of the docstring importer's present claims on a fact right now."""
    ontology = kb._kb
    entity = ontology.backend.get_entity_by_natural_key("default", "Fact", fact_key)
    if entity is None:
        return set()
    return {
        str(a.value)
        for a in ontology.assertions(subject=entity.id, predicate="Fact.value", status=None)
        if a.author == PRINCIPAL
        and a.valid_to is None
        and str(getattr(a.status, "value", a.status)) in _PRESENT
    }


@dataclass
class Replayed:
    kb: OntolithKnowledgeBase
    reports: dict[tuple[str, str], IngestReport]
    observed: dict[tuple[str, str, str], set[str]]


@pytest.fixture(scope="module")
def replayed(tmp_path_factory: pytest.TempPathFactory) -> Replayed:
    kb = OntolithKnowledgeBase.initialize(
        tmp_path_factory.mktemp("claims") / "kb.db",
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
    observed: dict[tuple[str, str, str], set[str]] = {}
    for step in HISTORY.steps:
        reports[(step.scenario.id, step.label)] = use_case.run(step.ref)
        scenario = step.scenario
        wanted = [(e.symbol, e.aspect) for e in scenario.expectations if e.commit == step.label]
        wanted += [(c.symbol, c.aspect) for c in scenario.claim_states if c.commit == step.label]
        for symbol, aspect in wanted:
            observed[(scenario.id, step.label, f"{symbol}#{aspect}")] = _present_values(
                kb, f"{symbol}#{aspect}"
            )
    return Replayed(kb, reports, observed)


@pytest.mark.parametrize(
    ("scenario", "exp"),
    _l2_cases(),
    ids=[f"{s.id}@{e.commit}:{e.aspect}" for s, e in _l2_cases()],
)
def test_the_kb_holds_the_docstring_claims_the_zoo_labels(
    replayed: Replayed, scenario: Scenario, exp: Expectation
) -> None:
    expected = {value for principal, value in exp.claims if principal == PRINCIPAL}
    actual = replayed.observed[(scenario.id, exp.commit, f"{exp.symbol}#{exp.aspect}")]
    assert actual == expected


@pytest.mark.parametrize(
    ("scenario", "state"),
    _claim_cases(),
    ids=[f"{s.id}@{c.commit}:{c.symbol.rsplit('.', 1)[-1]}" for s, c in _claim_cases()],
)
def test_the_kb_holds_the_claims_the_protocol_should_leave(
    replayed: Replayed, scenario: Scenario, state: ClaimsExpectation
) -> None:
    expected = {value for principal, value in state.claims if principal == PRINCIPAL}
    assert (
        replayed.observed[(scenario.id, state.commit, f"{state.symbol}#{state.aspect}")] == expected
    )


def test_the_zoo_labels_enough_docstring_claims() -> None:
    assert len(_l2_cases()) >= 10 and len(_claim_cases()) >= 8


def _history(kb: OntolithKnowledgeBase, fact_key: str) -> list[object]:
    ontology = kb._kb
    entity = ontology.backend.get_entity_by_natural_key("default", "Fact", fact_key)
    assert entity is not None, fact_key
    found = ontology.assertions(subject=entity.id, predicate="Fact.value", status=None)
    return sorted((a for a in found if a.author == PRINCIPAL), key=lambda a: a.valid_from)  # type: ignore[no-any-return]


class TestEditHistory:
    FACT = "py:docstring_edit.client.connect#param.timeout.default"

    def test_the_old_claim_is_retracted_at_the_commit_the_new_one_is_asserted(
        self, replayed: Replayed
    ) -> None:
        old, new = _history(replayed.kb, self.FACT)  # type: ignore[misc]
        c1, c2 = TIMES[("docstring_edit", "c1")], TIMES[("docstring_edit", "c2")]
        assert (str(old.status), old.value, old.valid_from, old.valid_to) == (
            "retracted",
            "30",
            c1,
            c2,
        )  # type: ignore[attr-defined]
        assert (str(new.status), new.value, new.valid_from, new.valid_to) == (
            "flagged",  # in a dispute with the projection of the code's 30: that is the drift
            "60",
            c2,
            None,
        )  # type: ignore[attr-defined]

    def test_an_edit_never_makes_an_author_contradict_itself(self, replayed: Replayed) -> None:
        """Retract-then-assert: the only dispute is docs against code, never docs against docs."""
        ontology = replayed.kb._kb
        entity = ontology.backend.get_entity_by_natural_key("default", "Fact", self.FACT)
        members = [
            c.member_ids
            for c in ontology.contradictions()
            if c.subject == entity.id and str(getattr(c.state, "value", c.state)) == "open"
        ]
        assert len(members) == 1
        authors = sorted(
            a.author
            for a in ontology.assertions(subject=entity.id, predicate="Fact.value", status=None)
            if a.id in members[0]
        )
        assert authors == [PRINCIPAL, "plumb-projector"]  # one claim each

    def test_provenance_points_at_the_documented_symbol_at_that_commit(
        self, replayed: Replayed
    ) -> None:
        _old, new = _history(replayed.kb, self.FACT)  # type: ignore[misc]
        sha = next(
            s.ref.sha
            for s in HISTORY.steps
            if s.scenario.id == "docstring_edit" and s.label == "c2"
        )
        assert (
            new.source
            == f"repo://zoo/zoo@{sha}/scenarios/docstring_edit/src/docstring_edit/client.py#sym=docstring_edit.client.connect"
        )  # type: ignore[attr-defined]
        assert "[docstring-claim-importer/1]" in new.rationale  # type: ignore[attr-defined]


class TestReports:
    def test_an_edit_reports_one_retraction_and_one_assertion(self, replayed: Replayed) -> None:
        report = replayed.reports[("docstring_edit", "c2")]
        assert (report.claims_retracted, report.claims_asserted) == (1, 1)

    def test_a_syntax_error_leaves_the_claims_and_changes_nothing(self, replayed: Replayed) -> None:
        report = replayed.reports[("docstring_syntax_error", "c2")]
        assert (report.claims_asserted, report.claims_retracted, report.deferred) == (0, 0, ())

    def test_deleting_a_file_retracts_what_it_claimed(self, replayed: Replayed) -> None:
        assert replayed.reports[("docstring_file_deleted", "c2")].claims_retracted >= 1

    def test_an_unchanged_commit_writes_no_claims(self, replayed: Replayed) -> None:
        report = replayed.reports[("drift_persists", "c3")]
        assert (report.claims_asserted, report.claims_retracted) == (0, 0)
