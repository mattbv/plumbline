"""Drift detection is Ontolith conflict routing -- there is no separate use
case that "computes" drift (PRD DRF-1/ADR-0001). What belongs here is the
one step around it that *is* Plumbline's own logic: classifying an open
contradiction's members into a `doc_vs_code` / `doc_vs_doc` /
`doc_vs_doc_vs_code` shape and attaching the introducing commit (PRD DRF-4).

This module is a deliberate placeholder for M1: the real implementation
reads `Ontology.query(Fact).where(...).include_flagged()` results through
`plumbline.adapters.ontolith_kb`, which the `KnowledgeBase` port above
doesn't expose yet -- widening that port is real M1 work, not scaffolding.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DriftKind(StrEnum):
    """How a contradiction's members are split by author kind (PRD DRF-4)."""

    DOC_VS_CODE = "doc_vs_code"
    DOC_VS_DOC = "doc_vs_doc"
    DOC_VS_DOC_VS_CODE = "doc_vs_doc_vs_code"


@dataclass(frozen=True, slots=True)
class DriftItem:
    """One open contradiction, classified and attributed."""

    fact_key: str
    kind: DriftKind
    introducing_commit: str
    member_values: tuple[str, ...]
