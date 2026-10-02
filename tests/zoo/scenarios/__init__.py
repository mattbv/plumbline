"""All drift-zoo scenarios, in one flat tuple."""

from __future__ import annotations

from ..model import Scenario
from . import abstention, closure, history, removal, signatures

ALL: tuple[Scenario, ...] = (
    *signatures.SCENARIOS,
    *abstention.SCENARIOS,
    *history.SCENARIOS,
    *closure.SCENARIOS,
    *removal.SCENARIOS,
)
