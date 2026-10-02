"""A pinnable clock for backfill (PRD §7.7).

Ontolith's ``as_of(t)`` needs both ``valid_from <= t`` and ``asserted_at <= t``.
If backfilled history were asserted at today's time, ``as_of(v2.3)`` would
return nothing. So during backfill the repository's history is treated as the
transaction log the KB is reconstructing: each write is *pinned* to its commit's
time, and the real ingest time is kept in metadata. In live mode the clock is
left unpinned and reports the real time.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ontolith.core.clock import Clock


class ReplayClock(Clock):
    """Reports a pinned instant when one is set, otherwise the real time."""

    def __init__(self) -> None:
        self._pinned: datetime | None = None

    def pin(self, when: datetime) -> None:
        """Make `now()` return `when` until `unpin()`."""
        if when.tzinfo is None:
            raise ValueError("replay times must be timezone-aware")
        self._pinned = when

    def unpin(self) -> None:
        """Return to reporting the real time."""
        self._pinned = None

    def now(self) -> datetime:
        """The pinned instant, or the real current time (UTC) if unpinned."""
        return self._pinned if self._pinned is not None else datetime.now(UTC)
