"""`OntolithKnowledgeBase` against a real Ontolith KB: lifecycle and failure modes."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from plumbline.adapters import ontolith_kb
from plumbline.adapters.ontolith_kb import OntolithKnowledgeBase
from plumbline.application.ports import RawClaim, RetractOutcome

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


def _claim(
    value: str, *, symbol: str = "py:m.f", aspect: str = "param.x.default", path: str = "README.md"
) -> RawClaim:
    anchor = f"repo://o/r@abcdef0123456789abcdef0123456789abcdef01/{path}#L1-L2"
    return RawClaim(symbol, aspect, value, anchor, 0.9, "md.table")


def _values(
    kb: OntolithKnowledgeBase, fact: str = "py:m.f#param.x.default"
) -> list[tuple[str, str, str]]:
    """``(author, value, status)`` for every claim on a fact."""
    o = kb._kb
    entity = o.backend.get_entity_by_natural_key("default", "Fact", fact)
    assert entity is not None
    found = o.assertions(subject=entity.id, predicate="Fact.value", status=None)
    return sorted(
        (a.author, str(a.value), str(getattr(a.status, "value", a.status))) for a in found
    )


class TestPrincipals:
    def test_init_registers_one_service_principal_per_source_kind(self, tmp_path: Path) -> None:
        kb = _kb(tmp_path / "kb.db")
        for name in (
            "plumb-code",
            "plumb-readme",
            "plumb-docs",
            "plumb-docstring",
            "plumb-changelog",
        ):
            principal = kb._kb.get_principal(name)
            assert principal is not None and str(principal.kind) in (
                "service",
                "PrincipalKind.SERVICE",
            )


class TestRecordClaim:
    def test_the_first_claim_creates_the_fact_with_its_aspect_and_symbol(
        self, tmp_path: Path
    ) -> None:
        kb = _kb(tmp_path / "kb.db")
        kb.record_code_fact("py:m.f", "present", "true", as_of=WHEN, source=SOURCE)
        kb.record_claim(_claim("30"), author_principal="plumb-readme", as_of=WHEN)

        o = kb._kb
        fact = o.backend.get_entity_by_natural_key("default", "Fact", "py:m.f#param.x.default")
        assert fact is not None
        rows = {a.predicate: a for a in o.assertions(subject=fact.id)}
        assert rows["Fact.aspect"].value == "param.x.default"
        symbol = o.backend.get_entity_by_natural_key("default", "Symbol", "py:m.f")
        assert (
            symbol is not None and rows["Fact.about"].value == symbol.id
        )  # the existing L1 symbol

    def test_a_claim_about_a_symbol_l1_never_saw_creates_an_empty_symbol(
        self, tmp_path: Path
    ) -> None:
        """So 'the README names something that does not exist' is recorded, not lost."""
        kb = _kb(tmp_path / "kb.db")
        kb.record_claim(
            _claim("true", symbol="py:m.ghost", aspect="exists"),
            author_principal="plumb-readme",
            as_of=WHEN,
        )
        assert kb.symbol_fields("py:m.ghost") == {}  # exists, but nothing is known about it
        assert kb.symbol_fields("py:m.other") is None

    def test_a_second_claim_reuses_the_fact_and_the_symbol(self, tmp_path: Path) -> None:
        kb = _kb(tmp_path / "kb.db")
        kb.record_claim(_claim("30"), author_principal="plumb-readme", as_of=WHEN)
        kb.record_claim(_claim("30", path="docs/a.md"), author_principal="plumb-docs", as_of=WHEN)
        assert _values(kb) == [("plumb-docs", "30", "active"), ("plumb-readme", "30", "active")]

    def test_agreeing_claims_coexist_and_a_disagreement_flags_every_member(
        self, tmp_path: Path
    ) -> None:
        kb = _kb(tmp_path / "kb.db")
        kb.record_claim(_claim("30"), author_principal="plumb-readme", as_of=WHEN)
        kb.record_claim(_claim("30", path="docs/a.md"), author_principal="plumb-docs", as_of=WHEN)
        kb.record_claim(_claim("45", path="a.py"), author_principal="plumb-docstring", as_of=WHEN)
        assert {status for *_, status in _values(kb)} == {"flagged"}

    def test_a_claim_from_a_principal_without_write_is_a_configuration_error(
        self, tmp_path: Path
    ) -> None:
        kb = _kb(tmp_path / "kb.db")
        kb._kb.create_principal(
            "weak-bot", kind="service", auth_method="workload", default_capability="propose"
        )
        with pytest.raises(RuntimeError, match="not auto-accepted"):
            kb.record_claim(_claim("30"), author_principal="weak-bot", as_of=WHEN)

    def test_replay_pins_assertion_time_to_the_commit(self, tmp_path: Path) -> None:
        kb = OntolithKnowledgeBase.initialize(
            tmp_path / "kb.db", admin_principal_id="admin@x.invalid", replay=True
        )
        kb.record_claim(_claim("30"), author_principal="plumb-readme", as_of=WHEN)
        o = kb._kb
        fact = o.backend.get_entity_by_natural_key("default", "Fact", "py:m.f#param.x.default")
        [claim] = o.assertions(subject=fact.id, predicate="Fact.value")
        assert claim.asserted_at == claim.valid_from == WHEN


class TestActiveClaims:
    def test_returns_present_claims_by_author_and_path(self, tmp_path: Path) -> None:
        kb = _kb(tmp_path / "kb.db")
        kb.record_claim(_claim("30"), author_principal="plumb-readme", as_of=WHEN)
        kb.record_claim(
            _claim("true", aspect="param.x.exists"), author_principal="plumb-readme", as_of=WHEN
        )
        kb.record_claim(_claim("30", path="docs/a.md"), author_principal="plumb-docs", as_of=WHEN)

        found = kb.active_claims("plumb-readme", ["README.md", "docs/a.md", "other.md"])

        assert sorted((c.fact_key, c.value) for c in found["README.md"]) == [
            ("py:m.f#param.x.default", "30"),
            ("py:m.f#param.x.exists", "true"),
        ]
        assert found["docs/a.md"] == [] and found["other.md"] == []

    def test_a_retracted_claim_is_no_longer_present(self, tmp_path: Path) -> None:
        kb = _kb(tmp_path / "kb.db")
        kb.record_claim(_claim("30"), author_principal="plumb-readme", as_of=WHEN)
        [claim] = kb.active_claims("plumb-readme", ["README.md"])["README.md"]
        kb.retract_claim(claim.claim_id, author_principal="plumb-readme", as_of=WHEN)
        assert kb.active_claims("plumb-readme", ["README.md"])["README.md"] == []

    def test_a_flagged_claim_in_a_dispute_is_still_present(self, tmp_path: Path) -> None:
        kb = _kb(tmp_path / "kb.db")
        kb.record_claim(_claim("30"), author_principal="plumb-readme", as_of=WHEN)
        kb.record_claim(_claim("45", path="docs/a.md"), author_principal="plumb-docs", as_of=WHEN)
        assert [c.value for c in kb.active_claims("plumb-readme", ["README.md"])["README.md"]] == [
            "30"
        ]


class TestRetractClaim:
    def test_an_undisputed_claim_is_withdrawn(self, tmp_path: Path) -> None:
        kb = _kb(tmp_path / "kb.db")
        kb.record_claim(_claim("30"), author_principal="plumb-readme", as_of=WHEN)
        [claim] = kb.active_claims("plumb-readme", ["README.md"])["README.md"]
        outcome = kb.retract_claim(claim.claim_id, author_principal="plumb-readme", as_of=WHEN)
        assert outcome is RetractOutcome.RETRACTED
        assert _values(kb) == [("plumb-readme", "30", "retracted")]

    def test_a_claim_in_an_open_dispute_cannot_be_withdrawn_by_its_author(
        self, tmp_path: Path
    ) -> None:
        """Ontolith refuses a party to a contradiction: the claim must stay for a human."""
        kb = _kb(tmp_path / "kb.db")
        kb.record_claim(_claim("30"), author_principal="plumb-readme", as_of=WHEN)
        kb.record_claim(_claim("45", path="docs/a.md"), author_principal="plumb-docs", as_of=WHEN)
        [claim] = kb.active_claims("plumb-docs", ["docs/a.md"])["docs/a.md"]

        outcome = kb.retract_claim(claim.claim_id, author_principal="plumb-docs", as_of=WHEN)

        assert outcome is RetractOutcome.DISPUTED
        assert ("plumb-docs", "45", "flagged") in _values(kb)  # untouched


class TestFactReads:
    """The reads the drift projector plans from (ADR-0007)."""

    def _kb_with_claims(self, tmp_path: Path) -> OntolithKnowledgeBase:
        kb = _kb(tmp_path / "kb.db")
        kb.record_claim(_claim("30"), author_principal="plumb-readme", as_of=WHEN)
        kb.record_claim(
            _claim("true", aspect="param.x.exists"), author_principal="plumb-readme", as_of=WHEN
        )
        kb.record_claim(
            _claim("true", symbol="py:m.f.inner", aspect="exists"),
            author_principal="plumb-readme",
            as_of=WHEN,
        )
        kb.record_claim(
            _claim("true", symbol="py:other.g", aspect="exists"),
            author_principal="plumb-readme",
            as_of=WHEN,
        )
        return kb

    def test_the_projector_principal_is_registered(self, tmp_path: Path) -> None:
        assert _kb(tmp_path / "kb.db")._kb.get_principal("plumb-projector") is not None

    def test_facts_about_a_symbol_are_exactly_its_own(self, tmp_path: Path) -> None:
        kb = self._kb_with_claims(tmp_path)
        assert kb.facts_about("py:m.f") == ["py:m.f#param.x.default", "py:m.f#param.x.exists"]
        assert kb.facts_about("py:nobody") == []

    def test_facts_under_a_namespace_are_its_descendants_only(self, tmp_path: Path) -> None:
        kb = self._kb_with_claims(tmp_path)
        assert kb.facts_under("py:m") == [
            "py:m.f#param.x.default", "py:m.f#param.x.exists", "py:m.f.inner#exists",
        ]  # fmt: skip
        assert kb.facts_under("py:m.f.inner") == []
        assert kb.facts_under("py:m.fo") == []  # a name prefix is not a namespace prefix

    def test_claims_on_a_fact_come_from_every_author(self, tmp_path: Path) -> None:
        kb = self._kb_with_claims(tmp_path)
        kb.record_claim(
            _claim("30", path="src/m.py"), author_principal="plumb-projector", as_of=WHEN
        )
        claims = kb.claims_on("py:m.f#param.x.default")
        assert [(c.author, c.value, c.path) for c in claims] == [
            ("plumb-projector", "30", "src/m.py"),
            ("plumb-readme", "30", "README.md"),
        ]

    def test_claims_on_excludes_withdrawn_ones_and_unknown_facts(self, tmp_path: Path) -> None:
        kb = self._kb_with_claims(tmp_path)
        [claim] = kb.claims_on("py:m.f#param.x.default")
        kb.retract_claim(claim.claim_id, author_principal="plumb-readme", as_of=WHEN)
        assert kb.claims_on("py:m.f#param.x.default") == []
        assert kb.claims_on("py:nope#exists") == []

    def test_a_flagged_claim_in_a_dispute_is_still_on_the_fact(self, tmp_path: Path) -> None:
        kb = self._kb_with_claims(tmp_path)
        kb.record_claim(
            _claim("45", path="src/m.py"), author_principal="plumb-projector", as_of=WHEN
        )
        assert {c.value for c in kb.claims_on("py:m.f#param.x.default")} == {"30", "45"}


class TestWithdrawCodeFact:
    def test_a_withdrawn_field_reads_as_not_stated(self, tmp_path: Path) -> None:
        kb = _kb(tmp_path / "kb.db")
        kb.record_code_fact("py:m.f", "kind", "function", as_of=WHEN, source=SOURCE)
        kb.record_code_fact("py:m.f", "signature_json", '{"v":1}', as_of=WHEN, source=SOURCE)
        kb.withdraw_code_fact("py:m.f", "signature_json", as_of=WHEN.replace(hour=2))
        assert kb.symbol_fields("py:m.f") == {"kind": "function"}

    def test_the_history_keeps_the_withdrawn_value_with_a_closed_window(
        self, tmp_path: Path
    ) -> None:
        kb = OntolithKnowledgeBase.initialize(
            tmp_path / "kb.db", admin_principal_id="a@x.invalid", replay=True
        )
        kb.record_code_fact("py:m.f", "signature_json", '{"v":1}', as_of=WHEN, source=SOURCE)
        kb.withdraw_code_fact("py:m.f", "signature_json", as_of=WHEN.replace(hour=2))
        o = kb._kb
        e = o.backend.get_entity_by_natural_key("default", "Symbol", "py:m.f")
        [a] = o.assertions(subject=e.id, predicate="Symbol.signature_json", status=None)
        assert (str(a.status), a.valid_from, a.valid_to) == (
            "retracted",
            WHEN,
            WHEN.replace(hour=2),
        )

    def test_a_field_can_be_stated_again_after_being_withdrawn(self, tmp_path: Path) -> None:
        kb = _kb(tmp_path / "kb.db")
        kb.record_code_fact("py:m.f", "signature_json", '{"v":1}', as_of=WHEN, source=SOURCE)
        kb.withdraw_code_fact("py:m.f", "signature_json", as_of=WHEN.replace(hour=2))
        kb.record_code_fact(
            "py:m.f",
            "signature_json",
            '{"v":1,"returns":"int"}',
            as_of=WHEN.replace(hour=3),
            source=SOURCE,
        )
        assert kb.symbol_fields("py:m.f") == {"signature_json": '{"v":1,"returns":"int"}'}

    def test_withdrawing_from_an_unknown_symbol_or_unset_field_is_a_no_op(
        self, tmp_path: Path
    ) -> None:
        kb = _kb(tmp_path / "kb.db")
        kb.withdraw_code_fact("py:nobody", "signature_json", as_of=WHEN)
        kb.record_code_fact("py:m.f", "kind", "function", as_of=WHEN, source=SOURCE)
        kb.withdraw_code_fact("py:m.f", "signature_json", as_of=WHEN)
        assert kb.symbol_fields("py:m.f") == {"kind": "function"}
