"""Abstract ports the use cases depend on (never a concrete adapter directly).

Each `Protocol` here is deliberately narrow -- a use case should be
constructible against a hand-written fake in a unit test with no real
Ontolith connection, no real Git repository, and no network access. See
ADR-0002 for why these are `Protocol`s rather than a shared `abc.ABC` base
(structural typing, matching Ontolith's own port style; PRD's own reference
to Ontolith's `StorageBackend`/`Clock` ports is the precedent this follows).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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


@dataclass(frozen=True, slots=True)
class CommitRef:
    """One commit on the tracked branch, as the ingestion pipeline sees it."""

    sha: str
    committed_at: datetime
    changed_paths: tuple[str, ...]


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
        """Return one file's raw bytes as of `commit_sha`."""
        ...


class CodeImporter(Protocol):
    """Extracts L1 code facts from a snapshot of source files (PRD ING-1).

    Static analysis only -- never imports or executes the files it's given.
    """

    def extract(self, files: dict[str, bytes], commit: CommitRef) -> list[RawClaim]:
        """Return the code facts (aspect claims about `Symbol`s) found at this commit."""
        ...


class DocImporter(Protocol):
    """Extracts doc claims from one kind of documentation source (PRD ING-2/3/4)."""

    def extract(self, files: dict[str, bytes], commit: CommitRef) -> list[RawClaim]:
        """Return the doc claims found in these files at this commit."""
        ...


class KnowledgeBase(Protocol):
    """The subset of Ontolith's `Ontology` the application layer actually needs.

    Implemented by `plumbline.adapters.ontolith_kb.OntolithKnowledgeBase`. Kept
    narrow and named in terms Plumbline's own use cases think in, rather than
    exposing the full `Ontology` surface here.
    """

    def record_code_fact(self, symbol_key: str, field: str, value: str, *, as_of: datetime) -> None:
        """Write an L1 `Symbol.*` fact -- always supersedes, never contradicts."""
        ...

    def record_claim(self, claim: RawClaim, *, author_principal: str, as_of: datetime) -> None:
        """Write an L2 `Fact.value` claim -- routes through static conflict handling."""
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
