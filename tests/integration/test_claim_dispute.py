"""An edit made while the claim is stuck in a dispute (ADR-0006 §3), against a real KB.

Ontolith refuses to let the importer withdraw a claim that is a member of an open
contradiction. The protocol therefore holds the change back (neither retract nor
assert a replacement), reports it, and lets a human decide; once they have, the
claim catches up on the next commit that touches the file.
"""

from __future__ import annotations

from pathlib import Path

from plumbline.adapters.docstring_claim_importer import PRINCIPAL, DocstringClaimImporter
from plumbline.adapters.ontolith_kb import OntolithKnowledgeBase
from plumbline.adapters.python_code_importer import PythonCodeImporter
from plumbline.application.ports import RawClaim
from plumbline.application.use_cases.ingest import DeferredClaim, IngestOneCommit
from tests.zoo.importing import ZooHistory
from tests.zoo.model import Commit, Scenario
from tests.zoo.scenarios._util import package, text

ID = "dispute_demo"
PATH = f"src/{ID}/client.py"
FACT = f"py:{ID}.client.connect#param.timeout.default"
SCOPED_PATH = f"scenarios/{ID}/{PATH}"


def _module(default: str, extra: str = "") -> str:
    return (
        text(f'''
        def connect(host, timeout=30):
            """Open.

            Args:
                host (str): Host.
                timeout (int): Seconds. Defaults to {default}.
            """
    ''')
        + extra
    )


SCENARIO = Scenario(
    id=ID,
    title="an edit during a dispute",
    prd_refs=("ADR-0006",),
    commits=(
        Commit("c1", "say 30", {**package(ID), PATH: _module("30")}),
        Commit("c2", "edit to say 60", {PATH: _module("60")}),
        Commit("c3", "touch the file again", {PATH: _module("60", "\n\nx = 1\n")}),
    ),
    expectations=(),
)


def _present(kb: OntolithKnowledgeBase) -> set[str]:
    return {
        c.value
        for c in kb.active_claims(PRINCIPAL, [SCOPED_PATH])[SCOPED_PATH]
        if c.fact_key == FACT
    }


def _dispute_authors(kb: OntolithKnowledgeBase) -> list[str]:
    """Authors of the members of every open contradiction, sorted."""
    ontology = kb._kb
    members = [
        ontology.get_assertion(i) if hasattr(ontology, "get_assertion") else None
        for c in ontology.contradictions()
        if str(getattr(c.state, "value", c.state)) == "open"
        for i in c.member_ids
    ]
    if any(m is None for m in members):  # fall back to scanning
        wanted = {
            i
            for c in ontology.contradictions()
            if str(getattr(c.state, "value", c.state)) == "open"
            for i in c.member_ids
        }
        return sorted(
            a.author
            for a in ontology.assertions(predicate="Fact.value", status=None)
            if a.id in wanted
        )
    return sorted(m.author for m in members if m is not None)


def _open_disputes(kb: OntolithKnowledgeBase) -> int:
    return len(
        [c for c in kb._kb.contradictions() if str(getattr(c.state, "value", c.state)) == "open"]
    )


def test_an_edit_during_a_dispute_is_deferred_then_catches_up_after_resolution(
    tmp_path: Path,
) -> None:
    kb = OntolithKnowledgeBase.initialize(
        tmp_path / "kb.db", admin_principal_id="admin@x.invalid", replay=True
    )
    history = ZooHistory([SCENARIO])
    use_case = IngestOneCommit(
        repo=history,
        code_importer=PythonCodeImporter("zoo", "zoo"),
        doc_importers=(DocstringClaimImporter("zoo", "zoo"),),
        kb=kb,
        repo_slug="zoo/zoo",
    )
    c1, c2, c3 = (step.ref for step in history.steps)

    use_case.run(c1)
    assert _present(kb) == {"30"} and _open_disputes(kb) == 0

    # Another documentation source disagrees: the docstring's 30 (and the projection of the
    # code's 30) are now members of an open dispute with the docs page's 45.
    kb.record_claim(
        RawClaim(
            f"py:{ID}.client.connect",
            "param.timeout.default",
            "45",
            f"repo://zoo/zoo@{'a' * 40}/docs/tuning.md#L1-L1",
            0.9,
            "md.table",
        ),
        author_principal="plumb-docs",
        as_of=c1.committed_at,
    )
    assert _open_disputes(kb) == 1
    assert _dispute_authors(kb) == sorted([PRINCIPAL, "plumb-docs", "plumb-projector"])

    # The docstring is edited to 60 while the dispute is open.
    report = use_case.run(c2)

    assert report.deferred == (DeferredClaim(PRINCIPAL, SCOPED_PATH, FACT),)
    assert (report.claims_asserted, report.claims_retracted) == (0, 0)
    assert _present(kb) == {"30"}  # not withdrawn, and no replacement piled on
    assert _open_disputes(kb) == 1

    # A human resolves, keeping the docstring's 30 and retracting the docs page's 45.
    kb._kb.create_principal(
        "alice@x.invalid",
        kind="human",
        auth_method="oidc",
        default_capability="review",
        trust_level=5,
        author="admin@x.invalid",
    )
    dispute = next(c for c in kb._kb.contradictions())
    winner = next(
        a
        for a in kb._kb.assertions(predicate="Fact.value", status=None)
        if a.author == PRINCIPAL and str(a.value) == "30"
    )
    kb._kb.resolve_contradiction(dispute.id, winner.id, "alice@x.invalid")
    assert _open_disputes(kb) == 0

    # The next commit that touches the file catches the claim up: retract 30, assert 60.
    report = use_case.run(c3)

    assert report.deferred == ()
    assert (report.claims_asserted, report.claims_retracted) == (1, 1)
    assert _present(kb) == {"60"}

    # The resolution retracted every member but the winner, including the projection of
    # the code's 30; the catch-up re-states it. The docstring now says 60 against code
    # that still says 30: that is genuine drift, and it opens a *new* dispute between
    # exactly those two -- not a self-contradiction, and not the old dispute reviving.
    assert report.projected == 1
    assert _open_disputes(kb) == 1
    assert _dispute_authors(kb) == sorted([PRINCIPAL, "plumb-projector"])
