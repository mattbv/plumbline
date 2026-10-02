"""Assembling importer claims into L1 Symbol fields (ADR-0004)."""

from __future__ import annotations

import pytest

from plumbline.application.ports import RawClaim
from plumbline.application.symbol_facts import SymbolFields, aspects_of, assemble

SHA = "abcdef0123456789abcdef0123456789abcdef01"


def claim(symbol: str, aspect: str, value: str, path: str = "src/pkg/mod.py") -> RawClaim:
    return RawClaim(symbol, aspect, value, f"repo://o/r@{SHA}/{path}#L1-L3", 1.0, "test")


METHOD = [
    claim("py:pkg.mod.C.m", "exists", "true"),
    claim("py:pkg.mod.C.m", "kind", "method"),
    claim("py:pkg.mod.C.m", "deprecated", "false"),
    claim("py:pkg.mod.C.m", "param_names", '["a"]'),
    claim("py:pkg.mod.C.m", "param.a.exists", "true"),
    claim("py:pkg.mod.C.m", "param.a.default", "1"),
    claim("py:pkg.mod.C.m", "raises.KeyError", "true"),
]


class TestAssemble:
    def test_a_method_gets_every_field(self) -> None:
        fields = assemble(METHOD)["py:pkg.mod.C.m"]
        assert fields.kind == "method"
        assert fields.present == "true"
        assert fields.is_deprecated == "false"
        assert fields.namespace_closed is None
        assert fields.defined_at == "src/pkg/mod.py"
        assert fields.signature_json == (
            '{"param_names":["a"],"params":{"a":{"default":"1"}},"raises":["KeyError"],"v":1}'
        )

    def test_defined_at_is_the_path_not_the_sha_pinned_anchor(self) -> None:
        fields = assemble(METHOD)["py:pkg.mod.C.m"]
        assert SHA not in fields.defined_at and "#" not in fields.defined_at

    def test_the_anchor_is_kept_as_provenance_but_is_not_a_field(self) -> None:
        fields = assemble(METHOD)["py:pkg.mod.C.m"]
        assert fields.anchor == f"repo://o/r@{SHA}/src/pkg/mod.py#L1-L3"
        assert "anchor" not in fields.as_mapping()

    def test_a_class_has_closure_and_no_blob(self) -> None:
        claims = [
            claim("py:pkg.mod.C", "exists", "true"),
            claim("py:pkg.mod.C", "kind", "class"),
            claim("py:pkg.mod.C", "deprecated", "false"),
            claim("py:pkg.mod.C", "namespace_closed", "true"),
        ]
        fields = assemble(claims)["py:pkg.mod.C"]
        assert fields.namespace_closed == "true" and fields.signature_json is None

    def test_an_attribute_is_just_present(self) -> None:
        fields = assemble(
            [claim("py:pkg.mod.X", "exists", "true"), claim("py:pkg.mod.X", "kind", "attribute")]
        )
        assert fields["py:pkg.mod.X"].as_mapping() == {
            "kind": "attribute",
            "present": "true",
            "defined_at": "src/pkg/mod.py",
        }

    def test_as_mapping_omits_fields_the_importer_made_no_claim_about(self) -> None:
        assert set(assemble(METHOD)["py:pkg.mod.C.m"].as_mapping()) == {
            "kind",
            "present",
            "defined_at",
            "is_deprecated",
            "signature_json",
        }

    def test_symbols_are_grouped_and_ordered_by_key(self) -> None:
        both = [
            claim("py:pkg.b", "exists", "true"),
            claim("py:pkg.b", "kind", "attribute"),
            claim("py:pkg.a", "exists", "true"),
            claim("py:pkg.a", "kind", "attribute"),
        ]
        assert list(assemble(both)) == ["py:pkg.a", "py:pkg.b"]

    def test_input_order_does_not_matter(self) -> None:
        assert assemble(METHOD) == assemble(reversed(METHOD))

    def test_no_claims_no_symbols(self) -> None:
        assert assemble([]) == {}

    @pytest.mark.parametrize(
        ("drop", "match"),
        [("exists", "needs both"), ("kind", "needs both")],
    )
    def test_missing_exists_or_kind_is_a_bug(self, drop: str, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            assemble([c for c in METHOD if c.aspect != drop])

    def test_unknown_kind(self) -> None:
        with pytest.raises(ValueError, match="unknown kind"):
            assemble([claim("py:p.x", "exists", "true"), claim("py:p.x", "kind", "widget")])

    def test_existence_is_only_ever_claimed_true(self) -> None:
        with pytest.raises(ValueError, match="only ever claims existence"):
            assemble([claim("py:p.x", "exists", "false"), claim("py:p.x", "kind", "attribute")])

    def test_duplicate_aspects_are_a_bug(self) -> None:
        with pytest.raises(ValueError, match="more than once"):
            assemble([*METHOD, claim("py:pkg.mod.C.m", "deprecated", "true")])

    def test_signature_facts_on_a_non_callable_are_a_bug(self) -> None:
        with pytest.raises(ValueError, match="cannot have signature facts"):
            assemble(
                [
                    claim("py:p.C", "exists", "true"),
                    claim("py:p.C", "kind", "class"),
                    claim("py:p.C", "returns.type", "int"),
                ]
            )


class TestAspectsOf:
    def test_is_the_inverse_of_assemble_for_a_method(self) -> None:
        expected = sorted((c.aspect, c.raw_value) for c in METHOD if c.aspect != "kind")
        assert aspects_of(assemble(METHOD)["py:pkg.mod.C.m"]) == expected

    def test_a_bare_symbol_only_exists(self) -> None:
        assert aspects_of(
            SymbolFields(kind="attribute", present="true", defined_at="x.py", anchor="a")
        ) == [("exists", "true")]


from plumbline.application.symbol_facts import (  # noqa: E402
    KeyConflict,
    emitting_paths,
    find_conflicts,
    kind_rank,
)


def at(path: str, symbol: str, kind: str) -> list[RawClaim]:
    anchor = f"repo://o/r@{SHA}/{path}#L1-L2"
    return [
        RawClaim(symbol, "exists", "true", anchor, 1.0, "t"),
        RawClaim(symbol, "kind", kind, anchor, 1.0, "t"),
    ]


class TestAmbiguous:
    def test_an_ambiguous_symbol_is_present_but_has_no_details(self) -> None:
        fields = assemble(at("src/m.py", "py:m.f", "ambiguous"))["py:m.f"]
        assert fields.kind == "ambiguous" and fields.present == "true"
        assert fields.signature_json is None and fields.is_deprecated is None

    def test_ambiguity_with_signature_facts_is_a_bug(self) -> None:
        claims = [
            *at("src/pkg/mod.py", "py:m.f", "ambiguous"),
            claim("py:m.f", "returns.type", "int"),
        ]
        with pytest.raises(ValueError, match="cannot have signature facts"):
            assemble(claims)

    def test_projection_of_an_ambiguous_symbol_is_just_existence(self) -> None:
        assert aspects_of(assemble(at("src/m.py", "py:m.f", "ambiguous"))["py:m.f"]) == [
            ("exists", "true")
        ]


class TestKeyOwnership:
    MODULE = at("pkg/sub.py", "py:pkg.sub", "module")
    ALIAS = at("pkg/__init__.py", "py:pkg.sub", "attribute")

    def test_ranks_order_module_over_definition_over_attribute(self) -> None:
        assert kind_rank("module") > kind_rank("function") > kind_rank("attribute")
        assert kind_rank("class") == kind_rank("method") == kind_rank("ambiguous")

    @pytest.mark.parametrize("order", ["module-first", "alias-first"])
    def test_a_module_beats_the_import_that_shares_its_key_in_either_order(
        self, order: str
    ) -> None:
        claims = (
            [*self.MODULE, *self.ALIAS] if order == "module-first" else [*self.ALIAS, *self.MODULE]
        )
        fields = assemble(claims)["py:pkg.sub"]
        assert (fields.kind, fields.defined_at) == ("module", "pkg/sub.py")

    def test_a_tie_goes_to_the_lexicographically_first_path(self) -> None:
        claims = [*at("b/x.py", "py:m.f", "function"), *at("a/x.py", "py:m.f", "function")]
        assert assemble(claims)["py:m.f"].defined_at == "a/x.py"

    def test_conflicts_name_the_winner_and_the_loser(self) -> None:
        assert find_conflicts([*self.ALIAS, *self.MODULE]) == [
            KeyConflict("py:pkg.sub", "pkg/sub.py", "pkg/__init__.py")
        ]

    def test_no_conflict_when_a_key_has_one_path(self) -> None:
        assert find_conflicts(METHOD) == []

    def test_emitting_paths_lists_every_path_per_key(self) -> None:
        assert emitting_paths([*self.ALIAS, *self.MODULE]) == {
            "py:pkg.sub": frozenset({"pkg/sub.py", "pkg/__init__.py"})
        }
