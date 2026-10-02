"""IngestOneCommit orchestration, tested against hand-written fakes -- no real
Ontolith connection, no real Git repository (PRD §9.4's determinism/testability
principle, applied one layer up)."""

from __future__ import annotations

from collections.abc import Collection
from datetime import UTC, datetime

from plumbline.application.ports import (
    ActiveClaim,
    CommitRef,
    DocExtraction,
    RawClaim,
    RetractOutcome,
)
from plumbline.application.use_cases.ingest import IngestOneCommit
from plumbline.domain import anchors

SHA = "abcdef0123456789abcdef0123456789abcdef01"
WHEN = datetime(2026, 1, 1, tzinfo=UTC)
ANCHOR = f"repo://acme/sdk@{SHA}/src/acme/client.py#L1-L4"


class FakeRepoReader:
    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files

    def first_parent_history(self, *, since: datetime | None = None) -> list[CommitRef]:
        return []

    def read_file_at(self, path: str, commit_sha: str) -> bytes:
        if path not in self._files:
            raise FileNotFoundError(path)
        return self._files[path]


class FakeCodeImporter:
    def __init__(self, claims: list[RawClaim]) -> None:
        self._claims = claims
        self.seen: list[dict[str, bytes]] = []

    def extract(self, files: dict[str, bytes], commit: CommitRef) -> list[RawClaim]:
        self.seen.append(files)
        return self._claims


class FakeDocImporter:
    """A doc importer that returns staged claims for the paths it is told it analyzed."""

    def __init__(
        self,
        claims: list[RawClaim] | None = None,
        *,
        principal: str = "plumb-readme",
        suffix: str = ".md",
        analyzed: frozenset[str] | None = None,
    ) -> None:
        self.claims = claims or []
        self.principal = principal
        self.suffix = suffix
        self.analyzed = analyzed

    def handles(self, path: str) -> bool:
        return path.endswith(self.suffix)

    def extract(self, files: dict[str, bytes], commit: CommitRef) -> DocExtraction:
        analyzed = (
            self.analyzed
            if self.analyzed is not None
            else frozenset(p for p in files if self.handles(p))
        )
        return DocExtraction(list(self.claims), analyzed)


class FakeKnowledgeBase:
    """Remembers writes, and answers reads from them like a real KB would."""

    def __init__(self, existing: dict[str, dict[str, str]] | None = None) -> None:
        self.symbols: dict[str, dict[str, str]] = dict(existing or {})
        self.writes: list[tuple[str, str, str, datetime, str]] = []
        self.claims: list[RawClaim] = []  # every claim ever recorded, in order
        self.events: list[tuple[str, str]] = []  # ("assert"|"retract", fact_key), in order
        self.stored: dict[str, tuple[str, str, str, str]] = {}  # id -> author, fact, value, path
        self.disputed_facts: set[str] = set()
        self._next = 0

    def symbol_fields(self, symbol_key: str) -> dict[str, str] | None:
        fields = self.symbols.get(symbol_key)
        return None if fields is None else dict(fields)

    def symbols_defined_in(self, path: str) -> list[str]:
        return sorted(
            key
            for key, fields in self.symbols.items()
            if fields.get("defined_at") == path and fields.get("present") == "true"
        )

    def record_code_fact(
        self, symbol_key: str, field: str, value: str, *, as_of: datetime, source: str
    ) -> None:
        self.writes.append((symbol_key, field, value, as_of, source))
        self.symbols.setdefault(symbol_key, {})[field] = value

    def record_claim(self, claim: RawClaim, *, author_principal: str, as_of: datetime) -> None:
        self._next += 1
        path = anchors.parse(claim.anchor_uri).path
        self.stored[f"c{self._next}"] = (author_principal, claim.fact_key, claim.raw_value, path)
        self.claims.append(claim)
        self.events.append(("assert", claim.fact_key))

    def active_claims(
        self, author_principal: str, paths: Collection[str]
    ) -> dict[str, list[ActiveClaim]]:
        found: dict[str, list[ActiveClaim]] = {path: [] for path in paths}
        for claim_id, (author, fact, value, path) in self.stored.items():
            if author == author_principal and path in found:
                found[path].append(ActiveClaim(claim_id, fact, value, path))
        return found

    def retract_claim(
        self, claim_id: str, *, author_principal: str, as_of: datetime
    ) -> RetractOutcome:
        fact = self.stored[claim_id][1]
        if fact in self.disputed_facts:
            return RetractOutcome.DISPUTED
        del self.stored[claim_id]
        self.events.append(("retract", fact))
        return RetractOutcome.RETRACTED


def _commit(*, changed: tuple[str, ...] = ("README.md",)) -> CommitRef:
    return CommitRef(sha=SHA, committed_at=WHEN, changed_paths=changed)


def _claim(aspect: str, value: str, symbol: str = "py:acme.client.connect") -> RawClaim:
    return RawClaim(symbol, aspect, value, ANCHOR, 1.0, "test")


def _function(default: str = "30") -> list[RawClaim]:
    return [
        _claim("exists", "true"),
        _claim("kind", "function"),
        _claim("deprecated", "false"),
        _claim("param_names", '["timeout"]'),
        _claim("param.timeout.exists", "true"),
        _claim("param.timeout.default", default),
    ]


def _use_case(
    kb: FakeKnowledgeBase,
    claims: list[RawClaim],
    files: dict[str, bytes] | None = None,
    docs: tuple[FakeDocImporter, ...] = (),
) -> IngestOneCommit:
    return IngestOneCommit(
        repo=FakeRepoReader(files or {"README.md": b""}),
        code_importer=FakeCodeImporter(claims),
        doc_importers=docs,
        kb=kb,
        repo_slug="o/r",
    )


class TestCodeFacts:
    def test_assembles_claims_into_symbol_fields_and_writes_each_one(self) -> None:
        kb = FakeKnowledgeBase()
        _use_case(kb, _function()).run(_commit())

        written = {(key, field): value for key, field, value, _, _ in kb.writes}
        assert written == {
            ("py:acme.client.connect", "kind"): "function",
            ("py:acme.client.connect", "present"): "true",
            ("py:acme.client.connect", "defined_at"): "src/acme/client.py",
            ("py:acme.client.connect", "is_deprecated"): "false",
            (
                "py:acme.client.connect",
                "signature_json",
            ): '{"param_names":["timeout"],"params":{"timeout":{"default":"30"}},"v":1}',
        }

    def test_each_write_carries_the_commit_time_and_definition_anchor(self) -> None:
        kb = FakeKnowledgeBase()
        _use_case(kb, _function()).run(_commit())
        assert {(as_of, source) for *_, as_of, source in kb.writes} == {(WHEN, ANCHOR)}

    def test_fields_are_written_in_a_fixed_order(self) -> None:
        kb = FakeKnowledgeBase()
        _use_case(kb, _function()).run(_commit())
        assert [field for _, field, *_ in kb.writes] == [
            "kind", "present", "defined_at", "is_deprecated", "signature_json",
        ]  # fmt: skip

    def test_re_ingesting_an_unchanged_commit_writes_nothing(self) -> None:
        kb = FakeKnowledgeBase()
        use_case = _use_case(kb, _function())
        use_case.run(_commit())
        count = len(kb.writes)
        use_case.run(_commit())
        assert len(kb.writes) == count

    def test_only_the_changed_field_is_written(self) -> None:
        kb = FakeKnowledgeBase()
        _use_case(kb, _function("30")).run(_commit())
        kb.writes.clear()

        _use_case(kb, _function("60")).run(_commit())

        assert [(key, field) for key, field, *_ in kb.writes] == [
            ("py:acme.client.connect", "signature_json")
        ]

    def test_a_symbol_the_kb_already_knows_is_diffed_not_rewritten(self) -> None:
        kb = FakeKnowledgeBase({"py:acme.client.connect": {"kind": "function", "present": "true"}})
        _use_case(kb, _function()).run(_commit())
        assert "kind" not in {field for _, field, *_ in kb.writes}
        assert "signature_json" in {field for _, field, *_ in kb.writes}

    def test_every_symbol_in_the_commit_is_handled(self) -> None:
        other = [
            RawClaim("py:acme.client", "exists", "true", ANCHOR, 1.0, "m"),
            RawClaim("py:acme.client", "kind", "module", ANCHOR, 1.0, "m"),
        ]
        kb = FakeKnowledgeBase()
        _use_case(kb, [*_function(), *other]).run(_commit())
        assert set(kb.symbols) == {"py:acme.client", "py:acme.client.connect"}

    def test_a_malformed_claim_set_is_a_bug_and_raises(self) -> None:
        kb = FakeKnowledgeBase()
        try:
            _use_case(kb, [_claim("param.timeout.default", "30")]).run(_commit())
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError("expected ValueError")
        assert kb.writes == []


class TestFiles:
    def test_importers_see_only_the_changed_files_that_exist(self) -> None:
        importer = FakeCodeImporter([])
        use_case = IngestOneCommit(
            repo=FakeRepoReader({"a.py": b"x = 1\n"}),
            code_importer=importer,
            doc_importers=(),
            kb=FakeKnowledgeBase(),
            repo_slug="o/r",
        )
        use_case.run(_commit(changed=("a.py", "deleted.py")))
        assert importer.seen == [{"a.py": b"x = 1\n"}]
