"""Abstract ports the use cases depend on (never a concrete adapter directly).

Each `Protocol` here is deliberately narrow -- a use case should be
constructible against a hand-written fake in a unit test with no real
Ontolith connection, no real Git repository, and no network access. See
ADR-0002 for why these are `Protocol`s rather than a shared `abc.ABC` base
(structural typing, matching Ontolith's own port style; PRD's own reference
to Ontolith's `StorageBackend`/`Clock` ports is the precedent this follows).
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RawClaim:
    """One extracted, not-yet-canonicalized statement from a doc or code source."""

    symbol_key: str
    aspect: str
    raw_value: str
    anchor_uri: str
    confidence: float
    rationale: str

    @property
    def fact_key(self) -> str:
        """The `Fact` natural key this claim is about: ``<symbol_key>#<aspect>`` (PRD §7.2)."""
        return f"{self.symbol_key}#{self.aspect}"


@dataclass(frozen=True, slots=True)
class CommitRef:
    """One commit on the tracked branch, as the ingestion pipeline sees it."""

    sha: str
    committed_at: datetime
    changed_paths: tuple[str, ...]
    """Every added, modified, or deleted path. A rename lists **both** the old and the
    new path (the reader runs Git with rename detection off), so a moved file's old
    symbols are seen to leave (ADR-0005)."""


class RepoReader(Protocol):
    """Reads a Git repository's tracked-branch history and file contents.

    Implemented by `plumbline.adapters.git_reader` in terms of a real Git
    repository; a test fake can implement it over an in-memory list of
    `CommitRef`s with no Git dependency at all.
    """

    def first_parent_history(self, *, since: datetime | None = None) -> list[CommitRef]:
        """Return commits on the tracked branch's first-parent history, oldest first."""
        ...

    def read_file_at(self, path: str, commit_sha: str) -> bytes:
        """Return one file's raw bytes as of `commit_sha`.

        Raises:
            FileNotFoundError: The path does not exist at that commit, e.g. it
                was deleted by the commit being ingested.
        """
        ...


class CodeImporter(Protocol):
    """Extracts L1 code facts from a snapshot of source files (PRD ING-1).

    Static analysis only -- never imports or executes the files it's given.
    """

    def extract(self, files: dict[str, bytes], commit: CommitRef) -> list[RawClaim]:
        """Return the code facts (aspect claims about `Symbol`s) found at this commit."""
        ...


@dataclass(frozen=True, slots=True)
class DocExtraction:
    """What a doc importer found, and which paths it actually analyzed.

    Knowing which paths were *analyzed* is what lets the apply protocol retract a
    claim the document no longer makes without ever inferring removal from a file
    the importer could not read (ADR-0006, reusing ADR-0005's reasoning).

    Attributes:
        claims: Resolved claims, each with a known ``symbol_key``.
        analyzed_paths: Paths the importer successfully analyzed this commit,
            including those that now yield no claims.
    """

    claims: list[RawClaim]
    analyzed_paths: frozenset[str]


class DocImporter(Protocol):
    """Extracts doc claims from one kind of documentation source (PRD ING-2/3/4).

    Pure: a function of the files it is given. It emits claims with a resolved
    ``symbol_key`` or nothing at all -- it never guesses (ADR-0006).
    """

    principal: str
    """The per-source-kind `service` principal that authors this importer's claims."""

    def handles(self, path: str) -> bool:
        """Whether ``path`` is a document this importer owns (used for deleted files)."""
        ...

    def extract(self, files: dict[str, bytes], commit: CommitRef) -> DocExtraction:
        """Return the claims in these files at this commit, and which paths were analyzed."""
        ...


@dataclass(frozen=True, slots=True)
class ActiveClaim:
    """One present doc claim in the KB (active, or flagged in an open dispute)."""

    claim_id: str
    fact_key: str
    value: str
    path: str


class RetractOutcome(StrEnum):
    """Result of asking the KB to withdraw a claim (ADR-0006 §3)."""

    RETRACTED = "retracted"
    DISPUTED = "disputed"
    """The claim is a member of an open contradiction; its author may not withdraw it."""


class KnowledgeBase(Protocol):
    """The subset of Ontolith's `Ontology` the application layer actually needs.

    Implemented by `plumbline.adapters.ontolith_kb.OntolithKnowledgeBase`. Kept
    narrow and named in terms Plumbline's own use cases think in, rather than
    exposing the full `Ontology` surface here.
    """

    def symbol_fields(self, symbol_key: str) -> dict[str, str] | None:
        """Return a symbol's *active* L1 values keyed by `Symbol` field name.

        Returns:
            ``None`` if the KB has no such symbol yet, else ``{field: value}``
            for every field with a currently open (not superseded) assertion.
        """
        ...

    def symbols_defined_in(self, path: str) -> list[str]:
        """Keys of the symbols whose active ``defined_at`` is ``path`` and that are present.

        Used to infer removals: the symbols a file used to define are compared with
        what it defines now (ADR-0005). Sorted, so callers are deterministic.
        """
        ...

    def record_code_fact(
        self, symbol_key: str, field: str, value: str, *, as_of: datetime, source: str
    ) -> None:
        """Write one L1 `Symbol.<field>` fact -- always supersedes, never contradicts.

        Creates the symbol if it does not exist yet. ``as_of`` is when the fact
        became true (the commit's time); ``source`` is the anchor URI of the
        definition, recorded as the assertion's provenance.
        """
        ...

    def record_claim(self, claim: RawClaim, *, author_principal: str, as_of: datetime) -> None:
        """Write an L2 `Fact.value` claim -- routes through static conflict handling.

        Creates the `Fact` (and an empty `Symbol` it is about, if L1 has never seen
        it) on first use.
        """
        ...

    def active_claims(
        self, author_principal: str, paths: Collection[str]
    ) -> dict[str, list[ActiveClaim]]:
        """Present claims authored by ``author_principal`` from each of ``paths``.

        One call covers a whole commit's paths so the KB is scanned once.
        """
        ...

    def retract_claim(
        self, claim_id: str, *, author_principal: str, as_of: datetime
    ) -> RetractOutcome:
        """Withdraw a claim, or report that it is disputed and cannot be withdrawn by its author."""
        ...


class ReviewSurface(Protocol):
    """Where a human actually resolves drift and approves doc fixes (PRD §7.6/§8.3).

    Implemented by `plumbline.adapters.github_review` against real GitHub
    PRs/check-runs; this port is what keeps the reconciliation use cases from
    depending on GitHub's API shape directly.
    """

    def open_check_run(self, commit_sha: str, introduced_drift: list[str]) -> str:
        """Open (or update) a check run reporting this commit's introduced drift.

        Returns:
            An identifier for the created check run.
        """
        ...

    def open_doc_fix_pull_request(self, proposal_id: str, diff: str) -> str:
        """Open a PR carrying a proposed doc fix, linked back to the proposal.

        Returns:
            The PR's URL.
        """
        ...
