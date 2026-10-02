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

from collections import defaultdict
from dataclasses import dataclass

from plumbline.application.ports import (
    ActiveClaim,
    CodeImporter,
    CommitRef,
    DocImporter,
    KnowledgeBase,
    RawClaim,
    RepoReader,
    RetractOutcome,
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
class DeferredClaim:
    """A doc change that was not applied because the old claim is under dispute (ADR-0006 §3).

    The importer may not withdraw its own claim once it is a member of an open
    contradiction, and asserting a replacement would only grow the dispute. So the
    change waits for a human resolution, and this record says so.
    """

    author: str
    path: str
    fact_key: str


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
        claims_asserted: Doc claims newly stated and written.
        claims_retracted: Doc claims no longer stated and withdrawn.
        deferred: Doc changes held back because the old claim is disputed.
    """

    written: int = 0
    removed: tuple[str, ...] = ()
    unanalyzed: tuple[str, ...] = ()
    conflicts: tuple[KeyConflict, ...] = ()
    claims_asserted: int = 0
    claims_retracted: int = 0
    deferred: tuple[DeferredClaim, ...] = ()


@dataclass(frozen=True, slots=True)
class _DocPlan:
    """One doc importer's wanted claims versus the KB's present ones, per analyzed path."""

    importer: DocImporter
    paths: list[str]
    wanted: dict[str, dict[tuple[str, str], RawClaim]]
    present: dict[str, set[tuple[str, str]]]
    existing: dict[str, list[ActiveClaim]]


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

        # 2-5. The projection's retract+assert is the drift projector's job (a
        # Reasoner, PRD §7.8). This use case owns the doc side: claims no longer
        # stated are retracted before new ones are asserted (§7.7 steps 3 and 5).
        asserted, retracted, deferred = self._apply_doc_claims(commit, files, deleted)
        return IngestReport(
            written=report.written,
            removed=report.removed,
            unanalyzed=report.unanalyzed,
            conflicts=report.conflicts,
            claims_asserted=asserted,
            claims_retracted=retracted,
            deferred=tuple(deferred),
        )

    def _apply_doc_claims(
        self, commit: CommitRef, files: dict[str, bytes], deleted: frozenset[str]
    ) -> tuple[int, int, list[DeferredClaim]]:
        """The set-difference protocol per ``(fact, author, path)`` (ADR-0006 §2-3)."""
        plans = [
            plan
            for importer in self.doc_importers
            if (plan := self._plan(importer, files, deleted, commit))
        ]

        # Pass 1: retract everything no longer stated, before anything is asserted.
        retracted = 0
        held: set[tuple[str, str, str]] = set()
        for plan in plans:
            for path in plan.paths:
                for existing in sorted(
                    plan.existing.get(path, []), key=lambda c: (c.fact_key, c.value)
                ):
                    if (existing.fact_key, existing.value) in plan.wanted.get(path, {}):
                        continue
                    outcome = self.kb.retract_claim(
                        existing.claim_id,
                        author_principal=plan.importer.principal,
                        as_of=commit.committed_at,
                    )
                    if outcome is RetractOutcome.RETRACTED:
                        retracted += 1
                    else:
                        held.add((plan.importer.principal, path, existing.fact_key))

        # Pass 2: assert what is newly stated -- but never a replacement for a
        # claim that is stuck in a dispute.
        asserted = 0
        for plan in plans:
            author = plan.importer.principal
            for path in plan.paths:
                for (fact_key, value), claim in sorted(plan.wanted.get(path, {}).items()):
                    if (fact_key, value) in plan.present[path] or (author, path, fact_key) in held:
                        continue
                    self.kb.record_claim(claim, author_principal=author, as_of=commit.committed_at)
                    asserted += 1

        return asserted, retracted, [DeferredClaim(a, p, f) for a, p, f in sorted(held)]

    def _plan(
        self,
        importer: DocImporter,
        files: dict[str, bytes],
        deleted: frozenset[str],
        commit: CommitRef,
    ) -> _DocPlan | None:
        """What one importer now states versus what the KB holds, per analyzed path."""
        extraction = importer.extract(files, commit)
        paths = sorted(extraction.analyzed_paths | {p for p in deleted if importer.handles(p)})
        if not paths:
            return None
        wanted: dict[str, dict[tuple[str, str], RawClaim]] = defaultdict(dict)
        for claim in extraction.claims:
            path = anchors.parse(claim.anchor_uri).path
            wanted[path].setdefault((claim.fact_key, claim.raw_value), claim)
        existing = self.kb.active_claims(importer.principal, paths)
        present = {path: {(c.fact_key, c.value) for c in existing.get(path, [])} for path in paths}
        return _DocPlan(importer, paths, dict(wanted), present, existing)

    def _apply_code_facts(
        self,
        commit: CommitRef,
        files: dict[str, bytes],
        deleted: frozenset[str],
        claims: list[RawClaim],
    ) -> IngestReport:
        """Write changed L1 fields, infer removals, and report what was left alone."""
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
