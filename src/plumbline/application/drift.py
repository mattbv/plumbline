"""The shape of a finding: one open contradiction, as a person reads it (PRD J1, DRF-4)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from plumbline.application.projection import PROJECTOR_PRINCIPAL

AUTHORITY = {
    PROJECTOR_PRINCIPAL: 1.0,
    "plumb-docstring": 0.9,
    "plumb-docs": 0.8,
    "plumb-readme": 0.8,
    "plumb-changelog": 0.7,
    "plumb-wiki": 0.5,
}
"""Per-source authority used to rank the review queue (PRD §7.6). Ranking only: it never
combines confidences into a stored value."""


class DriftClass(StrEnum):
    """Who is in the dispute (DRF-4)."""

    DOC_VS_CODE = "doc_vs_code"
    DOC_VS_DOC = "doc_vs_doc"
    DOC_VS_DOC_VS_CODE = "doc_vs_doc_vs_code"


@dataclass(frozen=True, slots=True)
class DriftClaim:
    """One member of a contradiction."""

    author: str
    value: str
    path: str
    source: str
    confidence: float


@dataclass(frozen=True, slots=True)
class DriftItem:
    """One open contradiction on a fact.

    Attributes:
        fact_key: ``<symbol key>#<aspect>``.
        drift_class: Doc vs code, doc vs doc, or both.
        opened_at: The commit time at which it opened.
        claims: Every member, projection included.
    """

    fact_key: str
    drift_class: DriftClass
    opened_at: datetime | None
    claims: tuple[DriftClaim, ...]

    @property
    def code_value(self) -> str | None:
        """What the code says, if the projector is a member."""
        return next((c.value for c in self.claims if c.author == PROJECTOR_PRINCIPAL), None)

    @property
    def score(self) -> float:
        """Rank key: the strongest non-code member, by confidence times authority."""
        return max(
            (
                c.confidence * AUTHORITY.get(c.author, 0.5)
                for c in self.claims
                if c.author != PROJECTOR_PRINCIPAL
            ),
            default=0.0,
        )


def classify(claims: tuple[DriftClaim, ...]) -> DriftClass:
    """Classify a contradiction by its members (DRF-4; PRD §14 #3 and #4)."""
    has_code = any(c.author == PROJECTOR_PRINCIPAL for c in claims)
    doc_values = {c.value for c in claims if c.author != PROJECTOR_PRINCIPAL}
    if not has_code:
        return DriftClass.DOC_VS_DOC
    return DriftClass.DOC_VS_DOC_VS_CODE if len(doc_values) > 1 else DriftClass.DOC_VS_CODE
