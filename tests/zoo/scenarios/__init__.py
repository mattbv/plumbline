"""All drift-zoo scenarios, in one flat tuple."""

from __future__ import annotations

from ..model import Scenario
from . import abstention, history, signatures

ALL: tuple[Scenario, ...] = (*signatures.SCENARIOS, *abstention.SCENARIOS, *history.SCENARIOS)
