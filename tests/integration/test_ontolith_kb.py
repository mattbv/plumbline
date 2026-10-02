"""`OntolithKnowledgeBase` against a real Ontolith KB: lifecycle and failure modes."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from plumbline.adapters import ontolith_kb
from plumbline.adapters.ontolith_kb import OntolithKnowledgeBase
from plumbline.application.ports import RawClaim

pytestmark = pytest.mark.integration

WHEN = datetime(2024, 1, 1, tzinfo=UTC)
SOURCE = "repo://o/r@abcdef0123456789abcdef0123456789abcdef01/src/m.py#L1-L2"


def _kb(path: Path) -> OntolithKnowledgeBase:
    return OntolithKnowledgeBase.initialize(path, admin_principal_id="admin@x.invalid")


def test_a_reopened_kb_remembers_what_was_written(tmp_path: Path) -> None:
    kb = _kb(tmp_path / "kb.db")
    kb.record_code_fact("py:m.f", "present", "true", as_of=WHEN, source=SOURCE)
    kb.close()

    reopened = OntolithKnowledgeBase.open(tmp_path / "kb.db")
    assert reopened.symbol_fields("py:m.f") == {"present": "true"}
    reopened.close()


def test_a_symbol_with_no_facts_yet_has_an_empty_field_set_not_none(tmp_path: Path) -> None:
    kb = _kb(tmp_path / "kb.db")
    kb.record_code_fact("py:m.f", "kind", "function", as_of=WHEN, source=SOURCE)
    assert kb.symbol_fields("py:m.f") == {"kind": "function"}
    assert kb.symbol_fields("py:m.other") is None


def test_boolean_fields_are_written_as_booleans(tmp_path: Path) -> None:
    kb = _kb(tmp_path / "kb.db")
    kb.record_code_fact("py:m.f", "is_deprecated", "true", as_of=WHEN, source=SOURCE)
    assert kb.symbol_fields("py:m.f") == {"is_deprecated": "true"}


def test_a_write_that_needs_review_is_a_configuration_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Importing what the code says must auto-land; if it doesn't, plumb-code is misconfigured."""
    kb = _kb(tmp_path / "kb.db")
    kb._kb.create_principal(
        "weak-bot", kind="service", auth_method="workload", default_capability="propose"
    )
    monkeypatch.setattr(ontolith_kb, "CODE_PRINCIPAL", "weak-bot")
    with pytest.raises(RuntimeError, match="not auto-accepted"):
        kb.record_code_fact("py:m.f", "present", "true", as_of=WHEN, source=SOURCE)


def test_doc_claims_are_not_implemented_yet(tmp_path: Path) -> None:
    claim = RawClaim("py:m.f#exists", "exists", "true", SOURCE, 0.9, "t")
    with pytest.raises(NotImplementedError):
        _kb(tmp_path / "kb.db").record_claim(claim, author_principal="plumb-readme", as_of=WHEN)
