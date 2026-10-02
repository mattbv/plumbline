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


class TestSymbolsDefinedIn:
    """The path -> symbols lookup that removal detection rests on (ADR-0005)."""

    def _write(
        self,
        kb: OntolithKnowledgeBase,
        key: str,
        path: str,
        *,
        present: str = "true",
        at: datetime = WHEN,
    ) -> None:
        kb.record_code_fact(key, "defined_at", path, as_of=at, source=SOURCE)
        kb.record_code_fact(key, "present", present, as_of=at, source=SOURCE)

    def test_lists_exactly_the_present_symbols_of_that_path_sorted(self, tmp_path: Path) -> None:
        kb = _kb(tmp_path / "kb.db")
        self._write(kb, "py:m.b", "src/m.py")
        self._write(kb, "py:m.a", "src/m.py")
        self._write(kb, "py:other.x", "src/other.py")
        assert kb.symbols_defined_in("src/m.py") == ["py:m.a", "py:m.b"]

    def test_excludes_removed_symbols(self, tmp_path: Path) -> None:
        kb = _kb(tmp_path / "kb.db")
        self._write(kb, "py:m.a", "src/m.py")
        self._write(kb, "py:m.gone", "src/m.py")
        kb.record_code_fact(
            "py:m.gone", "present", "false", as_of=WHEN.replace(hour=5), source=SOURCE
        )
        assert kb.symbols_defined_in("src/m.py") == ["py:m.a"]

    def test_a_symbol_that_moved_is_listed_under_its_new_path_only(self, tmp_path: Path) -> None:
        kb = _kb(tmp_path / "kb.db")
        self._write(kb, "py:m.a", "src/old.py")
        kb.record_code_fact(
            "py:m.a", "defined_at", "src/new.py", as_of=WHEN.replace(hour=5), source=SOURCE
        )
        assert kb.symbols_defined_in("src/old.py") == []
        assert kb.symbols_defined_in("src/new.py") == ["py:m.a"]

    def test_an_unknown_path_has_no_symbols(self, tmp_path: Path) -> None:
        assert _kb(tmp_path / "kb.db").symbols_defined_in("nope.py") == []
