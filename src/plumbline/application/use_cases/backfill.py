"""Replay a repository's history through the ingest use case (PRD ING-8).

History is applied oldest-first into a fresh knowledge base. The loop is resumable:
ingesting a commit is idempotent (an unchanged field writes nothing), so a run that
stopped part-way through a commit can safely start that commit again.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from plumbline.application.ports import CommitRef, RepoReader
from plumbline.application.use_cases.ingest import IngestOneCommit, IngestReport


class HistoryRewritten(RuntimeError):
    """The commit a previous run stopped at is no longer on the tracked branch."""


@dataclass(slots=True)
class IngestTotals:
    """What a whole run did, summed over its commits."""

    commits: int = 0
    l1_writes: int = 0
    removed: int = 0
    claims_asserted: int = 0
    claims_retracted: int = 0
    projected: int = 0
    projections_withdrawn: int = 0
    abstained: int = 0
    fields_withdrawn: int = 0
    conflicts: int = 0
    deferred: int = 0
    unanalyzed: set[str] = field(default_factory=set)

    def add(self, report: IngestReport) -> None:
        """Fold one commit's report into the totals."""
        self.commits += 1
        self.l1_writes += report.written
        self.removed += len(report.removed)
        self.claims_asserted += report.claims_asserted
        self.claims_retracted += report.claims_retracted
        self.projected += report.projected
        self.projections_withdrawn += report.projections_withdrawn
        self.abstained += report.abstained
        self.fields_withdrawn += report.fields_withdrawn
        self.conflicts += len(report.conflicts)
        self.deferred += len(report.deferred)
        self.unanalyzed.update(report.unanalyzed)


@dataclass(slots=True)
class BackfillHistory:
    """Applies a repository's first-parent history, oldest first."""

    reader: RepoReader
    ingest: IngestOneCommit

    def run(
        self,
        *,
        after: str | None = None,
        since: datetime | None = None,
        limit: int | None = None,
        on_commit: Callable[[CommitRef, IngestReport], None] | None = None,
    ) -> IngestTotals:
        """Ingest every commit after ``after`` (a SHA from a previous run), up to ``limit``.

        Raises:
            HistoryRewritten: ``after`` is not on the branch any more.
        """
        history = self.reader.first_parent_history(since=since)
        if after is not None:
            shas = [c.sha for c in history]
            if after not in shas:
                raise HistoryRewritten(after)
            history = history[shas.index(after) + 1 :]
        totals = IngestTotals()
        for commit in history[:limit]:
            report = self.ingest.run(commit)
            totals.add(report)
            if on_commit is not None:
                on_commit(commit, report)
        return totals
