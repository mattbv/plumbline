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
            ("100.0", "100"),
            ("-3.0", "-3"),
            ("0.0", "0"),
            ("1.5", "1.5"),
            ("1e20", "1e+20"),  # too large to be written as an integer sensibly
            ("True", "True"),
            ("False", "False"),
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
    def canon(self, text: str) -> str:
        return canonical.canonical_type_annotation(text)

    def test_simple_type_is_unchanged(self) -> None:
        assert self.canon("int") == "int"

    def test_incidental_whitespace_is_collapsed(self) -> None:
        assert self.canon("dict[ str ,  int ]") == "dict[str, int]"

    def test_union_order_is_normalized(self) -> None:
        assert self.canon("str | int") == self.canon("int | str") == "int | str"

    @pytest.mark.parametrize(
        ("written", "expected"),
        [
            ("'Segment'", "Segment"),
            ("Iterable['Segment']", "Iterable[Segment]"),
            ('Dict["str", "int"]', "dict[str, int]"),
            ("Optional['Segment']", "None | Segment"),
        ],
    )
    def test_quotation_marks_are_removed_anywhere(self, written: str, expected: str) -> None:
        assert self.canon(written) == expected

    @pytest.mark.parametrize(
        ("written", "expected"),
        [
            ("typing.List[int]", "list[int]"),
            ("typing_extensions.Dict[str, int]", "dict[str, int]"),
            ("List[int]", "list[int]"),
            ("Tuple[int, ...]", "tuple[int, ...]"),
            ("Set[str]", "set[str]"),
            ("FrozenSet[str]", "frozenset[str]"),
            ("Type[Exception]", "type[Exception]"),
            ("Iterable[int]", "Iterable[int]"),  # not a builtin generic: left as written
        ],
    )
    def test_builtin_generics_are_spelled_the_same_way(self, written: str, expected: str) -> None:
        assert self.canon(written) == expected

    @pytest.mark.parametrize(
        ("written", "expected"),
        [
            ("Optional[int]", "None | int"),
            ("int | None", "None | int"),
            ("None | int", "None | int"),
            ("Union[str, int, None]", "None | int | str"),
            ("Optional[Union[str, int]]", "None | int | str"),
            ("Dict[str, Optional[int]]", "dict[str, None | int]"),
            ("List[int | None]", "list[None | int]"),
            ("Optional['Segment']", "None | Segment"),
        ],
    )
    def test_none_is_a_member_like_any_other(self, written: str, expected: str) -> None:
        assert self.canon(written) == expected

    def test_a_type_with_and_without_none_are_different_types(self) -> None:
        """PRD §14 #10: docs that say `int` for an `int | None` parameter omit something."""
        assert self.canon("int") != self.canon("int | None")

    def test_a_type_that_is_only_none_is_kept(self) -> None:
        assert self.canon("None") == "None"

    def test_repeated_members_collapse(self) -> None:
        assert self.canon("int | int | None") == "None | int"

    @pytest.mark.parametrize(
        "written", ["Literal['a', 'b']", "Literal['head', 'row', 'foot']", "Literal[1, 2]"]
    )
    def test_literal_values_are_not_types_and_are_left_alone(self, written: str) -> None:
        assert self.canon(written) == written

    def test_a_literal_inside_a_union_keeps_its_values(self) -> None:
        assert self.canon("Optional[Literal['a', 'b']]") == "Literal['a', 'b'] | None"

    @pytest.mark.parametrize(
        ("one", "other"),
        [
            ("int", "str"),
            ("list[int]", "Iterable[int]"),
            ("list[int]", "list[str]"),
            ("dict[str, int]", "dict[int, str]"),
            ("int | str", "int | bytes"),
            ("Style", "Segment"),
        ],
    )
    def test_different_types_stay_different(self, one: str, other: str) -> None:
        assert self.canon(one) != self.canon(other)

    @pytest.mark.parametrize(
        "written",
        ["os.PathLike[str]", "collections.abc.Iterable[int]", "Callable[..., int]", "'List[int'"],
    )
    def test_names_it_cannot_interpret_are_left_as_written(self, written: str) -> None:
        """A dotted name outside typing, `...`, or a forward reference that is not a type."""
        assert self.canon(written) == written

    def test_a_bare_tuple_expression_is_canonicalized_member_by_member(self) -> None:
        assert self.canon("List['int'], Optional[str]") == "(list[int], None | str)"

    def test_empty_parameter_lists_survive(self) -> None:
        assert self.canon("Callable[[], int]") == "Callable[[], int]"

    def test_text_that_is_not_an_expression_only_has_its_whitespace_collapsed(self) -> None:
        assert self.canon("the  next   release") == "the next release"

    @pytest.mark.parametrize(
        "written",
        ["int", "List['Segment'] | None", "Dict[str, Optional[int]]", "Literal['a'] | int", "None"],
    )
    def test_the_form_is_a_fixed_point(self, written: str) -> None:
        once = self.canon(written)
        assert self.canon(once) == once


class TestCanonicalVersion:
    @pytest.mark.parametrize("version", ["2.3.0", "v2.3.0", "1.0", "1.0.0rc1"])
    def test_valid_versions_are_accepted(self, version: str) -> None:
        assert canonical.canonical_version(version) is not None

    def test_v_prefix_is_stripped(self) -> None:
        assert canonical.canonical_version("v2.3.0") == "2.3.0"

    def test_non_version_text_abstains(self) -> None:
        assert canonical.canonical_version("the next release") is None


class TestCanonicalParamNames:
    def test_compact_json_in_declaration_order(self) -> None:
        assert canonical.canonical_param_names(["host", "timeout", "**opts"]) == (
            '["host","timeout","**opts"]'
        )

    def test_empty_signature(self) -> None:
        assert canonical.canonical_param_names([]) == "[]"

    def test_order_is_significant(self) -> None:
        assert canonical.canonical_param_names(["a", "b"]) != canonical.canonical_param_names(
            ["b", "a"]
        )
