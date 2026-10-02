"""The doc-claim apply protocol (ADR-0006), against fakes.

Per ``(fact, author, path)``: retract what is no longer stated *before* asserting
what is newly stated; do nothing for the unchanged; defer anything under dispute;
and never infer removal from a file that was not analyzed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from plumbline.application.ports import CommitRef, RawClaim
from plumbline.application.use_cases.ingest import DeferredClaim, IngestOneCommit
from tests.unit.application.test_ingest import FakeCodeImporter, FakeDocImporter, FakeKnowledgeBase

SHA = "abcdef0123456789abcdef0123456789abcdef01"
WHEN = datetime(2026, 1, 1, tzinfo=UTC)


class Repo:
    def __init__(self, present: set[str]) -> None:
        self.present = present

    def first_parent_history(self, *, since: datetime | None = None) -> list[CommitRef]:
        return []

    def read_file_at(self, path: str, commit_sha: str) -> bytes:
        if path not in self.present:
            raise FileNotFoundError(path)
        return b""


def claim(
    value: str, *, path: str = "README.md", aspect: str = "param.timeout.default"
) -> RawClaim:
    return RawClaim(
        "py:acme.client.connect", aspect, value, f"repo://o/r@{SHA}/{path}#L1-L2", 0.9, "md.table"
    )


def run(
    kb: FakeKnowledgeBase,
    importers: list[FakeDocImporter],
    changed: list[str],
    *,
    exists: list[str] | None = None,
):
    use_case = IngestOneCommit(
        repo=Repo(set(changed if exists is None else exists)),
        code_importer=FakeCodeImporter([]),
        doc_importers=tuple(importers),
        kb=kb,
        repo_slug="o/r",
    )
    return use_case.run(CommitRef(SHA, WHEN, tuple(changed)))


FACT = "py:acme.client.connect#param.timeout.default"


class TestApply:
    def test_newly_stated_claims_are_asserted_under_the_importers_principal(self) -> None:
        kb = FakeKnowledgeBase()
        report = run(kb, [FakeDocImporter([claim("30")])], ["README.md"])

        assert report.claims_asserted == 1 and report.claims_retracted == 0
        assert [(a, f, v) for a, f, v, _ in kb.stored.values()] == [("plumb-readme", FACT, "30")]

    def test_re_ingesting_the_same_claims_writes_nothing(self) -> None:
        kb = FakeKnowledgeBase()
        importer = FakeDocImporter([claim("30")])
        run(kb, [importer], ["README.md"])
        again = run(kb, [importer], ["README.md"])

        assert (again.claims_asserted, again.claims_retracted) == (0, 0)
        assert len(kb.stored) == 1

    def test_an_edit_retracts_the_old_value_before_asserting_the_new_one(self) -> None:
        """Asserting first would make the author contradict itself (ADR-0006)."""
        kb = FakeKnowledgeBase()
        run(kb, [FakeDocImporter([claim("30")])], ["README.md"])
        kb.events.clear()

        report = run(kb, [FakeDocImporter([claim("60")])], ["README.md"])

        assert kb.events == [("retract", FACT), ("assert", FACT)]
        assert (report.claims_asserted, report.claims_retracted) == (1, 1)
        assert [v for _, _, v, _ in kb.stored.values()] == ["60"]

    def test_a_claim_no_longer_stated_is_retracted(self) -> None:
        kb = FakeKnowledgeBase()
        run(kb, [FakeDocImporter([claim("30")])], ["README.md"])
        report = run(kb, [FakeDocImporter([])], ["README.md"])
        assert report.claims_retracted == 1 and kb.stored == {}

    def test_unchanged_claims_in_an_edited_file_are_left_alone(self) -> None:
        kb = FakeKnowledgeBase()
        both = [claim("30"), claim("true", aspect="param.timeout.exists")]
        run(kb, [FakeDocImporter(both)], ["README.md"])
        report = run(kb, [FakeDocImporter([both[1]])], ["README.md"])
        assert (report.claims_asserted, report.claims_retracted) == (0, 1)

    def test_the_same_claim_twice_in_one_file_is_one_claim(self) -> None:
        kb = FakeKnowledgeBase()
        report = run(kb, [FakeDocImporter([claim("30"), claim("30")])], ["README.md"])
        assert report.claims_asserted == 1

    def test_two_values_for_one_fact_in_one_file_are_two_claims(self) -> None:
        """A document that contradicts itself is real drift."""
        kb = FakeKnowledgeBase()
        report = run(kb, [FakeDocImporter([claim("30"), claim("45")])], ["README.md"])
        assert report.claims_asserted == 2

    def test_the_same_value_from_two_files_is_two_claims(self) -> None:
        kb = FakeKnowledgeBase()
        importer = FakeDocImporter([claim("30", path="README.md"), claim("30", path="docs/a.md")])
        assert run(kb, [importer], ["README.md", "docs/a.md"]).claims_asserted == 2


class TestAnalysisAndDeletion:
    def test_a_file_the_importer_did_not_analyze_is_never_treated_as_emptied(self) -> None:
        kb = FakeKnowledgeBase()
        run(kb, [FakeDocImporter([claim("30")])], ["README.md"])

        silent = FakeDocImporter([], analyzed=frozenset())  # e.g. the file failed to parse
        report = run(kb, [silent], ["README.md"])

        assert report.claims_retracted == 0 and len(kb.stored) == 1

    def test_deleting_a_file_retracts_every_claim_it_authored(self) -> None:
        kb = FakeKnowledgeBase()
        run(kb, [FakeDocImporter([claim("30"), claim("1", aspect="returns.type")])], ["README.md"])
        report = run(kb, [FakeDocImporter([], analyzed=frozenset())], ["README.md"], exists=[])
        assert report.claims_retracted == 2 and kb.stored == {}

    def test_only_the_importer_that_owns_a_deleted_path_retracts_its_claims(self) -> None:
        kb = FakeKnowledgeBase()
        readme = FakeDocImporter([claim("30")], principal="plumb-readme", suffix=".md")
        docstrings = FakeDocImporter(
            [claim("30", path="a.py")], principal="plumb-docstring", suffix=".py"
        )
        run(kb, [readme, docstrings], ["README.md", "a.py"])

        # a.py is deleted: a real importer finds nothing in a file that is gone.
        gone = FakeDocImporter([], principal="plumb-docstring", suffix=".py")
        report = run(kb, [readme, gone], ["a.py"], exists=[])

        assert report.claims_retracted == 1
        assert {a for a, *_ in kb.stored.values()} == {"plumb-readme"}

    def test_authors_are_independent(self) -> None:
        kb = FakeKnowledgeBase()
        readme = FakeDocImporter([claim("30")], principal="plumb-readme")
        docs = FakeDocImporter([claim("30", path="docs/a.md")], principal="plumb-docs")
        report = run(kb, [readme, docs], ["README.md", "docs/a.md"])
        assert report.claims_asserted == 2
        assert {a for a, *_ in kb.stored.values()} == {"plumb-readme", "plumb-docs"}

    def test_every_retraction_precedes_every_assertion_across_importers(self) -> None:
        kb = FakeKnowledgeBase()
        run(
            kb,
            [
                FakeDocImporter([claim("30")], principal="plumb-readme"),
                FakeDocImporter(
                    [claim("30", path="a.py")], principal="plumb-docstring", suffix=".py"
                ),
            ],
            ["README.md", "a.py"],
        )
        kb.events.clear()
        run(
            kb,
            [
                FakeDocImporter([claim("60")], principal="plumb-readme"),
                FakeDocImporter(
                    [claim("60", path="a.py")], principal="plumb-docstring", suffix=".py"
                ),
            ],
            ["README.md", "a.py"],
        )
        assert [kind for kind, _ in kb.events] == ["retract", "retract", "assert", "assert"]


class TestDisputedClaims:
    def test_a_disputed_claim_is_not_withdrawn_and_no_replacement_is_asserted(self) -> None:
        kb = FakeKnowledgeBase()
        run(kb, [FakeDocImporter([claim("30")])], ["README.md"])
        kb.disputed_facts.add(FACT)

        report = run(kb, [FakeDocImporter([claim("60")])], ["README.md"])

        assert report.deferred == (DeferredClaim("plumb-readme", "README.md", FACT),)
        assert (report.claims_asserted, report.claims_retracted) == (0, 0)
        assert [v for _, _, v, _ in kb.stored.values()] == ["30"]  # untouched

    def test_removing_a_disputed_claim_is_also_deferred(self) -> None:
        kb = FakeKnowledgeBase()
        run(kb, [FakeDocImporter([claim("30")])], ["README.md"])
        kb.disputed_facts.add(FACT)
        report = run(kb, [FakeDocImporter([])], ["README.md"])
        assert [d.fact_key for d in report.deferred] == [FACT]

    def test_other_facts_in_the_same_file_still_apply(self) -> None:
        kb = FakeKnowledgeBase()
        exists = claim("true", aspect="param.timeout.exists")
        run(kb, [FakeDocImporter([claim("30"), exists])], ["README.md"])
        kb.disputed_facts.add(FACT)

        report = run(
            kb,
            [FakeDocImporter([claim("60"), claim("false", aspect="param.timeout.exists")])],
            ["README.md"],
        )

        assert [d.fact_key for d in report.deferred] == [FACT]
        assert (report.claims_asserted, report.claims_retracted) == (1, 1)

    def test_an_unchanged_disputed_claim_is_not_reported(self) -> None:
        kb = FakeKnowledgeBase()
        run(kb, [FakeDocImporter([claim("30")])], ["README.md"])
        kb.disputed_facts.add(FACT)
        assert run(kb, [FakeDocImporter([claim("30")])], ["README.md"]).deferred == ()

    def test_a_brand_new_claim_on_a_disputed_fact_is_still_asserted(self) -> None:
        """Only a *replacement* for a stuck claim waits; a new statement joins the dispute."""
        kb = FakeKnowledgeBase()
        kb.disputed_facts.add(FACT)
        report = run(kb, [FakeDocImporter([claim("30")])], ["README.md"])
        assert report.claims_asserted == 1 and report.deferred == ()
