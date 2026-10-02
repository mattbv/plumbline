"""The ingestion use case: the commit-apply protocol (PRD §7.7).

Each commit is applied in a fixed order so transient intermediate states
never create false contradictions: L1 code facts first, then retract
stale L2 projections and claims, then assert the new ones. See ADR-0001
for why L1 and L2 need this ordering at all.

L1 handling follows ADR-0004 (claims are assembled into coarse ``Symbol``
fields and only changes are written) and ADR-0005 (a key has one owner, and
removal is inferred only for symbols a *changed* file owned). Every uncertain
case leaves the KB as it was: that can delay a true drift report, never invent one.
"""

from __future__ import annotations

from dataclasses import dataclass

from plumbline.application.ports import (
    CodeImporter,
    CommitRef,
    DocImporter,
    KnowledgeBase,
    RawClaim,
    RepoReader,
)
from plumbline.application.symbol_facts import (
    KeyConflict,
    SymbolFields,
    assemble,
    emitting_paths,
    find_conflicts,
    kind_rank,
)
from plumbline.domain import anchors
from plumbline.domain.anchors import Anchor


@dataclass(frozen=True, slots=True)
class IngestReport:
    """What one commit did, including the cases that were deliberately left alone.

    Attributes:
        written: Number of L1 field writes.
        removed: Symbols marked ``present = false`` by this commit.
        unanalyzed: Changed paths that still define known symbols but produced no
            module symbol (e.g. a file that no longer parses). Their symbols were
            left untouched.
        conflicts: Symbol keys claimed by more than one path, and who lost.
    """

    written: int = 0
    removed: tuple[str, ...] = ()
    unanalyzed: tuple[str, ...] = ()
    conflicts: tuple[KeyConflict, ...] = ()


@dataclass(slots=True)
class IngestOneCommit:
    """Applies one commit through the fixed six-step commit-apply protocol.

    Attributes:
        repo: Reads the tracked branch.
        code_importer: Extracts L1 facts.
        doc_importers: Extract doc claims.
        kb: The knowledge base.
        repo_slug: ``owner/repo``, used to anchor removals.
    """

    repo: RepoReader
    code_importer: CodeImporter
    doc_importers: tuple[DocImporter, ...]
    kb: KnowledgeBase
    repo_slug: str

    def run(self, commit: CommitRef) -> IngestReport:
        """Apply `commit` to the KB (PRD §7.7, steps 1-5; step 6 is `ReconcileDrift`)."""
        files, deleted = self._read_changed_files(commit)
        claims = self.code_importer.extract(files, commit)
        report = self._apply_code_facts(commit, files, deleted, claims)

        # 2-5. Projection/claim retract+assert is the drift projector's job
        # (a Reasoner, PRD §7.8) -- not this use case's. IngestOneCommit's
        # own responsibility ends at getting L1 and raw doc claims into the
        # KB; ReconcileDrift (M1) runs the projector and claim bookkeeping
        # this docstring's steps 2-5 describe.
        for importer in self.doc_importers:
            for claim in importer.extract(files, commit):
                self.kb.record_claim(
                    claim, author_principal="plumb-doc-importer", as_of=commit.committed_at
                )
        return report

    def _apply_code_facts(
        self,
        commit: CommitRef,
        files: dict[str, bytes],
        deleted: frozenset[str],
        claims: list[RawClaim],
    ) -> IngestReport:
        snapshot = assemble(claims)
        emitters = emitting_paths(claims)
        analyzed = frozenset(
            anchors.parse(c.anchor_uri).path
            for c in claims
            if c.aspect == "kind" and c.raw_value == "module"
        )

        written = 0
        conflicts = list(find_conflicts(claims))
        for symbol_key, fields in snapshot.items():
            current = self.kb.symbol_fields(symbol_key) or {}
            if not _may_write(
                fields, current, deleted, analyzed, emitters.get(symbol_key, frozenset())
            ):
                conflicts.append(KeyConflict(symbol_key, current["defined_at"], fields.defined_at))
                continue
            for field_name, value in fields.as_mapping().items():
                if current.get(field_name) != value:
                    self.kb.record_code_fact(
                        symbol_key,
                        field_name,
                        value,
                        as_of=commit.committed_at,
                        source=fields.anchor,
                    )
                    written += 1

        removed = self._remove_vanished(commit, snapshot, deleted | analyzed)
        unanalyzed = tuple(
            path for path in sorted(set(files) - analyzed) if self.kb.symbols_defined_in(path)
        )
        return IngestReport(
            written=written + len(removed),
            removed=tuple(removed),
            unanalyzed=unanalyzed,
            conflicts=tuple(conflicts),
        )

    def _remove_vanished(
        self, commit: CommitRef, snapshot: dict[str, SymbolFields], paths: frozenset[str]
    ) -> list[str]:
        """Mark ``present = false`` for symbols a deleted/analyzed path used to own."""
        removed: list[str] = []
        for path in sorted(paths):
            for key in self.kb.symbols_defined_in(path):
                if key in snapshot or _under_ambiguous(key, snapshot):
                    continue
                self.kb.record_code_fact(
                    key,
                    "present",
                    "false",
                    as_of=commit.committed_at,
                    source=self._removal_anchor(commit, path),
                )
                removed.append(key)
        return removed

    def _removal_anchor(self, commit: CommitRef, path: str) -> str:
        """Where and when absence was observed: this commit, that path, line 1."""
        owner, _, repo = self.repo_slug.partition("/")
        return Anchor("repo", owner, repo, commit.sha, path, 1, 1).to_uri()

    def _read_changed_files(self, commit: CommitRef) -> tuple[dict[str, bytes], frozenset[str]]:
        """Contents of every changed path that exists, and the set of deleted paths."""
        files: dict[str, bytes] = {}
        deleted: set[str] = set()
        for path in commit.changed_paths:
            try:
                files[path] = self.repo.read_file_at(path, commit.sha)
            except FileNotFoundError:
                deleted.add(path)  # nothing to read, but whatever it defined is gone
        return files, frozenset(deleted)


def _may_write(
    fields: SymbolFields,
    current: dict[str, str],
    deleted: frozenset[str],
    analyzed: frozenset[str],
    emitted_by: frozenset[str],
) -> bool:
    """Whether the incoming claims may touch a symbol the KB already has (ADR-0005 rule 1).

    A key has one owner, the path in its active ``defined_at``. The owner always
    may write. Another path may only take over if the key is free (removed, or its
    owner's file was deleted / re-analyzed without defining it), or if it outranks
    the owner's kind (a module beats an import that re-exports it). Otherwise the
    claim is dropped and reported.
    """
    owner = current.get("defined_at")
    if owner is None or owner == fields.defined_at or current.get("present") == "false":
        return True
    owner_gone = owner in deleted or (owner in analyzed and owner not in emitted_by)
    return owner_gone or kind_rank(fields.kind) > kind_rank(current.get("kind", "attribute"))


def _under_ambiguous(key: str, snapshot: dict[str, SymbolFields]) -> bool:
    """Whether an ancestor of ``key`` is defined more than once (its members are unknowable)."""
    parent = key
    while "." in parent:
        parent = parent.rpartition(".")[0]
        ancestor = snapshot.get(parent)
        if ancestor is not None and ancestor.kind == "ambiguous":
            return True
    return False
