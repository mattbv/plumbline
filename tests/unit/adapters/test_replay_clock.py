"""The pinnable clock behind backfill's replay semantics (PRD §7.7)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from plumbline.adapters.replay_clock import ReplayClock

T = datetime(2024, 1, 1, 12, tzinfo=UTC)


def test_unpinned_clock_reports_real_time() -> None:
    before = datetime.now(UTC)
    assert before <= ReplayClock().now() <= datetime.now(UTC)


def test_pinned_clock_reports_the_pinned_instant_until_unpinned() -> None:
    clock = ReplayClock()
    clock.pin(T)
    assert clock.now() == T == clock.now()
    clock.unpin()
    assert clock.now() != T


def test_repinning_moves_the_clock() -> None:
    clock = ReplayClock()
    clock.pin(T)
    clock.pin(datetime(2025, 1, 1, tzinfo=UTC))
    assert clock.now().year == 2025


def test_naive_times_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ReplayClock().pin(datetime(2024, 1, 1))
