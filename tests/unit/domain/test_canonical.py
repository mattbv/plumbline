"""Canonicalization must be deterministic and order-insensitive where specified
(PRD §9.4) -- these are exactly the properties a canonicalization bug would
violate, and exactly the properties `.CANONICALIZER_VERSION` bumps promise
to preserve."""

from __future__ import annotations

import pytest

from plumbline.domain import canonical


class TestCanonicalBool:
    def test_true_and_false(self) -> None:
        assert canonical.canonical_bool(True) == "true"
        assert canonical.canonical_bool(False) == "false"


class TestCanonicalLiteral:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("30", "30"),
            ("'utf-8'", "'utf-8'"),
            ("None", "None"),
            ("True", "True"),
        ],
    )
    def test_literal_values_round_trip(self, source: str, expected: str) -> None:
        assert canonical.canonical_literal(source) == expected

    def test_non_literal_expression_abstains(self) -> None:
        """A default referencing a name (not a literal) can't be safely
        evaluated -- the projector must abstain, never guess (PRD §7.4)."""
        assert canonical.canonical_literal("DEFAULT_TIMEOUT") is None

    def test_malformed_expression_abstains(self) -> None:
        assert canonical.canonical_literal("(( unbalanced") is None


class TestCanonicalTypeAnnotation:
    def test_simple_type_is_unchanged(self) -> None:
        assert canonical.canonical_type_annotation("int") == "int"

    def test_union_order_is_normalized(self) -> None:
        """`int | None` and `None | int` must canonicalize identically, or a
        docstring and an annotation that mean the same thing would drift
        against each other for no real reason (PRD Worked Example #10)."""
        assert canonical.canonical_type_annotation(
            "int | None"
        ) == canonical.canonical_type_annotation("None | int")

    def test_incidental_whitespace_is_collapsed(self) -> None:
        assert canonical.canonical_type_annotation("int  |   None") == "None | int"


class TestCanonicalVersion:
    @pytest.mark.parametrize("version", ["2.3.0", "v2.3.0", "1.0", "1.0.0rc1"])
    def test_valid_versions_are_accepted(self, version: str) -> None:
        assert canonical.canonical_version(version) is not None

    def test_v_prefix_is_stripped(self) -> None:
        assert canonical.canonical_version("v2.3.0") == "2.3.0"

    def test_non_version_text_abstains(self) -> None:
        assert canonical.canonical_version("the next release") is None
