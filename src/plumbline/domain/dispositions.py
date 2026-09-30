"""Resolution dispositions (PRD §7.6).

A disposition is Plumbline's own classification of *why* a contradiction was
resolved a particular way, layered on top of Ontolith's `resolve_contradiction`
(which only records a winner). Ontolith has no notion of "disposition" --
this is product-level metadata Plumbline attaches to the resolution event's
rationale and, where applicable, mirrors into a `Waiver` entity.
"""

from __future__ import annotations

from enum import StrEnum


class Disposition(StrEnum):
    """Why a human resolved a contradiction the way they did."""

    DOCS_STALE = "docs_stale"
    """The code projection is correct; the losing doc claim(s) are out of date."""

    CODE_DEFECT = "code_defect"
    """The doc claim is correct; the code regressed. Produces a Waiver (§7.6)."""

    DOC_VS_DOC = "doc_vs_doc"
    """Multiple doc sources disagreed with each other, independent of code."""

    EXTRACTION_ERROR = "extraction_error"
    """The claim was never really there -- an extractor bug. Feeds precision metrics."""

    INTENTIONAL_SIMPLIFICATION = "intentional_simplification"
    """The docs deliberately omit or simplify a true-but-noisy detail."""

    @property
    def creates_waiver(self) -> bool:
        """Whether this disposition produces a `Waiver` suppressing re-projection."""
        return self in (Disposition.CODE_DEFECT, Disposition.INTENTIONAL_SIMPLIFICATION)
