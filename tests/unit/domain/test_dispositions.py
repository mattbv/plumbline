from __future__ import annotations

from plumbline.domain.dispositions import Disposition


class TestCreatesWaiver:
    def test_code_defect_creates_a_waiver(self) -> None:
        assert Disposition.CODE_DEFECT.creates_waiver is True

    def test_intentional_simplification_creates_a_waiver(self) -> None:
        assert Disposition.INTENTIONAL_SIMPLIFICATION.creates_waiver is True

    def test_docs_stale_does_not_create_a_waiver(self) -> None:
        """docs_stale means the code projection won outright -- there's
        nothing to waive, the doc-fix proposal (REC-4) is the follow-up."""
        assert Disposition.DOCS_STALE.creates_waiver is False

    def test_extraction_error_does_not_create_a_waiver(self) -> None:
        assert Disposition.EXTRACTION_ERROR.creates_waiver is False
