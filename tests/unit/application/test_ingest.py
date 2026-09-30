"""IngestOneCommit orchestration, tested against hand-written fakes -- no real
Ontolith connection, no real Git repository (PRD §9.4's determinism/testability
principle, applied one layer up)."""

from __future__ import annotations

from datetime import UTC, datetime

from plumbline.application.ports import CommitRef, RawClaim
from plumbline.application.use_cases.ingest import IngestOneCommit


class FakeRepoReader:
    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files

    def first_parent_history(self, *, since: datetime | None = None) -> list[CommitRef]:
        return []

    def read_file_at(self, path: str, commit_sha: str) -> bytes:
        return self._files[path]


class FakeCodeImporter:
    def __init__(self, claims: list[RawClaim]) -> None:
        self._claims = claims

    def extract(self, files: dict[str, bytes], commit: CommitRef) -> list[RawClaim]:
        return self._claims


class FakeDocImporter:
    def __init__(self, claims: list[RawClaim]) -> None:
        self._claims = claims

    def extract(self, files: dict[str, bytes], commit: CommitRef) -> list[RawClaim]:
        return self._claims


class FakeKnowledgeBase:
    def __init__(self) -> None:
        self.code_facts: list[tuple[str, str, str]] = []
        self.claims: list[RawClaim] = []

    def record_code_fact(self, symbol_key: str, field: str, value: str, *, as_of: datetime) -> None:
        self.code_facts.append((symbol_key, field, value))

    def record_claim(self, claim: RawClaim, *, author_principal: str, as_of: datetime) -> None:
        self.claims.append(claim)


def _commit(*, changed: tuple[str, ...] = ("README.md",)) -> CommitRef:
    return CommitRef(
        sha="abc123", committed_at=datetime(2026, 1, 1, tzinfo=UTC), changed_paths=changed
    )


class TestIngestOneCommit:
    def test_writes_code_facts_from_the_code_importer(self) -> None:
        code_claim = RawClaim(
            symbol_key="py:acme.Client.connect",
            aspect="param.timeout.default",
            raw_value="30",
            anchor_uri="repo://acme/sdk@abc123/src/client.py#sym=acme.Client.connect",
            confidence=1.0,
            rationale="signature",
        )
        kb = FakeKnowledgeBase()
        use_case = IngestOneCommit(
            repo=FakeRepoReader({"README.md": b""}),
            code_importer=FakeCodeImporter([code_claim]),
            doc_importers=(),
            kb=kb,
        )

        use_case.run(_commit())

        assert kb.code_facts == [("py:acme.Client.connect", "param.timeout.default", "30")]
        assert kb.claims == []

    def test_writes_doc_claims_from_every_doc_importer(self) -> None:
        readme_claim = RawClaim(
            symbol_key="py:acme.Client.connect#param.timeout.default",
            aspect="param.timeout.default",
            raw_value="30",
            anchor_uri="repo://acme/sdk@abc123/README.md#L88-L91",
            confidence=0.9,
            rationale="md.table:config-defaults row 'timeout'",
        )
        changelog_claim = RawClaim(
            symbol_key="py:acme.Client.connect#added_in",
            aspect="added_in",
            raw_value="1.0",
            anchor_uri="repo://acme/sdk@abc123/CHANGELOG.md#L1-L1",
            confidence=0.9,
            rationale="keep-a-changelog",
        )
        kb = FakeKnowledgeBase()
        use_case = IngestOneCommit(
            repo=FakeRepoReader({"README.md": b"", "CHANGELOG.md": b""}),
            code_importer=FakeCodeImporter([]),
            doc_importers=(FakeDocImporter([readme_claim]), FakeDocImporter([changelog_claim])),
            kb=kb,
        )

        use_case.run(_commit(changed=("README.md", "CHANGELOG.md")))

        assert kb.claims == [readme_claim, changelog_claim]
