"""Every labeled routing outcome in the drift zoo, checked against a real Ontolith KB.

This is M0's exit criterion made executable: ingest the zoo commit by commit through
the whole pipeline -- the real code importer, the real docstring importer, the drift
projector, and Ontolith's static conflict routing -- and after each commit read the
outcome off the KB and compare it with the scenario's label.

Documents other than docstrings (README, docs pages, CHANGELOG) come from label-driven
stand-ins, because those importers do not exist yet (see ``tests/zoo/standins.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pytest
from ontolith.core.ids import SequentialIdProvider

from plumbline.adapters.docstring_claim_importer import DocstringClaimImporter
from plumbline.adapters.ontolith_kb import OntolithKnowledgeBase
from plumbline.adapters.python_code_importer import PythonCodeImporter
from plumbline.application.projection import PROJECTOR_PRINCIPAL
from plumbline.application.use_cases.ingest import IngestOneCommit, IngestReport
from plumbline.domain.projection import is_projectable
from tests.zoo.builder import timeline
from tests.zoo.importing import ZooHistory
from tests.zoo.model import DriftClass, Expectation, Layer, Outcome, Scenario
from tests.zoo.scenarios import ALL
from tests.zoo.standins import LabeledClaimImporter

pytestmark = pytest.mark.integration

HISTORY = ZooHistory(ALL)
TIMES = timeline(ALL)


def _cases() -> list[tuple[Scenario, Expectation]]:
    return [
        (s, e)
        for s in ALL
        for e in s.expectations
        if e.layer is Layer.L2 and e.symbol.startswith("py:") and is_projectable(e.aspect)
    ]


@dataclass(frozen=True)
class Observed:
    outcome: Outcome
    projection: str | None
    docs: frozenset[tuple[str, str]]
    drift_class: DriftClass | None
    opened_at: datetime | None


def _observe(kb: OntolithKnowledgeBase, fact_key: str) -> Observed:
    """Read a fact's routing outcome off the KB (ADR-0007 §7)."""
    claims = kb.claims_on(fact_key)
    docs = [c for c in claims if c.author != PROJECTOR_PRINCIPAL]
    projections = [c for c in claims if c.author == PROJECTOR_PRINCIPAL]
    if not docs:
        assert not projections, "a projection must not outlive the last doc claim"
        return Observed(Outcome.UNDOCUMENTED, None, frozenset(), None, None)

    doc_set = frozenset((c.author, c.value) for c in docs)
    projection = projections[0].value if projections else None
    if not projections:
        return Observed(Outcome.ABSTAIN, None, doc_set, None, None)

    ontology = kb._kb
    fact = ontology.backend.get_entity_by_natural_key("default", "Fact", fact_key)
    open_disputes = [
        c
        for c in ontology.contradictions()
        if c.subject == fact.id and str(getattr(c.state, "value", c.state)) == "open"
    ]
    if not open_disputes:
        return Observed(Outcome.CORROBORATE, projection, doc_set, None, None)
    [dispute] = open_disputes
    members = {c.claim_id: c for c in claims}
    flagged = [members[i] for i in dispute.member_ids if i in members]
    doc_values = {c.value for c in flagged if c.author != PROJECTOR_PRINCIPAL}
    drift = DriftClass.DOC_VS_DOC_VS_CODE if len(doc_values) > 1 else DriftClass.DOC_VS_CODE
    return Observed(Outcome.CONTRADICT, projection, doc_set, drift, dispute.created_at)


@dataclass
class Replayed:
    kb: OntolithKnowledgeBase
    reports: dict[tuple[str, str], IngestReport]
    observed: dict[tuple[str, str, str], Observed]


@pytest.fixture(scope="module")
def replayed(tmp_path_factory: pytest.TempPathFactory) -> Replayed:
    kb = OntolithKnowledgeBase.initialize(
        tmp_path_factory.mktemp("outcomes") / "kb.db",
        admin_principal_id="admin@zoo.invalid",
        replay=True,
        id_provider=SequentialIdProvider(prefix="id"),
    )
    use_case = IngestOneCommit(
        repo=HISTORY,
        code_importer=PythonCodeImporter("zoo", "zoo"),
        doc_importers=(
            DocstringClaimImporter("zoo", "zoo"),
            LabeledClaimImporter("plumb-readme", HISTORY),
            LabeledClaimImporter("plumb-docs", HISTORY),
            LabeledClaimImporter("plumb-changelog", HISTORY),
        ),
        kb=kb,
        repo_slug="zoo/zoo",
    )
    reports: dict[tuple[str, str], IngestReport] = {}
    observed: dict[tuple[str, str, str], Observed] = {}
    for step in HISTORY.steps:
        reports[(step.scenario.id, step.label)] = use_case.run(step.ref)
        for exp in step.scenario.expectations:
            if (
                exp.commit == step.label
                and exp.layer is Layer.L2
                and exp.symbol.startswith("py:")
                and is_projectable(exp.aspect)
            ):
                observed[(step.scenario.id, step.label, f"{exp.symbol}#{exp.aspect}")] = _observe(
                    kb, f"{exp.symbol}#{exp.aspect}"
                )
    return Replayed(kb, reports, observed)


@pytest.mark.parametrize(
    ("scenario", "exp"),
    _cases(),
    ids=[f"{s.id}@{e.commit}:{e.symbol.rsplit('.', 1)[-1]}#{e.aspect}" for s, e in _cases()],
)
def test_the_kb_routes_each_slot_as_the_zoo_labels_it(
    replayed: Replayed, scenario: Scenario, exp: Expectation
) -> None:
    got = replayed.observed[(scenario.id, exp.commit, f"{exp.symbol}#{exp.aspect}")]

    assert got.outcome is exp.outcome
    assert got.docs == frozenset(exp.claims)
    if exp.outcome in (Outcome.CORROBORATE, Outcome.CONTRADICT):
        assert got.projection == exp.code_value
    if exp.outcome is Outcome.CONTRADICT:
        assert got.drift_class is exp.drift_class
        introduced = TIMES[(scenario.id, exp.introduced_in or exp.commit)]
        assert got.opened_at == introduced


def test_the_zoo_covers_every_outcome_through_the_whole_pipeline() -> None:
    cases = _cases()
    assert {e.outcome for _, e in cases} == {
        Outcome.CORROBORATE, Outcome.CONTRADICT, Outcome.ABSTAIN, Outcome.UNDOCUMENTED,
    }  # fmt: skip
    assert len(cases) >= 40


class TestReports:
    def test_a_projection_stuck_in_a_dispute_is_deferred_and_reported(
        self, replayed: Replayed
    ) -> None:
        """The code changed under an open dispute: a human must see that (ADR-0007 §3)."""
        report = replayed.reports[("dispute_outlives_its_premise", "c2")]
        assert [(d.author, d.fact_key) for d in report.deferred] == [
            ("plumb-projector", "py:dispute_outlives_its_premise.api.missing#exists")
        ]
        assert report.projections_withdrawn == 0

    def test_a_projection_not_in_a_dispute_is_withdrawn_when_it_becomes_unprovable(
        self, replayed: Replayed
    ) -> None:
        opened = replayed.reports[("namespace_opens_and_closes", "c2")]
        closed = replayed.reports[("namespace_opens_and_closes", "c3")]
        assert (opened.projections_withdrawn, opened.deferred, opened.abstained) == (1, (), 1)
        assert (closed.projected, closed.abstained) == (1, 0)

    def test_fixing_code_and_docs_together_withdraws_and_restates_without_a_dispute(
        self, replayed: Replayed
    ) -> None:
        report = replayed.reports[("fixed_together", "c2")]
        assert (report.projections_withdrawn, report.projected) == (1, 1)
        assert (report.claims_retracted, report.claims_asserted) == (1, 1)
        assert report.deferred == ()

    def test_an_abstention_is_counted(self, replayed: Replayed) -> None:
        assert replayed.reports[("decorated_function", "c1")].abstained >= 1
