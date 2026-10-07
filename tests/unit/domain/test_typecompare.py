"""When a type disagreement is provable, and when it is left alone (ADR-0007 Amendments 3, 4)."""

from __future__ import annotations

import pytest

from plumbline.domain import canonical, typecompare


def canon(text: str) -> str:
    return canonical.canonical_type_annotation(text)


def provable(code: str, doc: str) -> bool:
    return typecompare.is_provable_difference(canon(code), canon(doc))


class TestWhatIsReported:
    @pytest.mark.parametrize(
        ("code", "doc"),
        [
            ("int", "str"),
            ("list[int]", "list[str]"),
            ("list[int]", "dict[int, int]"),
            ("dict[str, int]", "dict[int, str]"),
            ("int | str", "int | bytes"),
            ("float", "bytes"),
            ("bool", "str"),
        ],
    )
    def test_a_disagreement_made_only_of_resolved_names_is_reported(
        self, code: str, doc: str
    ) -> None:
        assert provable(code, doc)

    def test_docs_that_omit_none_are_reported(self) -> None:
        """PRD §14 #10: the annotation allows None and the docstring does not say so."""
        assert provable("int | None", "int")
        assert provable("Optional[Callable[[int], str]]", "Callable[[int], str]")

    def test_a_disagreement_on_the_other_members_is_still_reported_when_none_also_differs(
        self,
    ) -> None:
        assert provable("int", "str | None")
        assert provable("int | None", "str")

    def test_equal_types_are_not_a_difference(self) -> None:
        assert not provable("int | None", "Optional[int]")
        assert not provable("List['int']", "list[int]")


class TestWhatIsLeftAlone:
    def test_docs_that_allow_none_where_the_code_does_not_abstain(self) -> None:
        """`x (int, optional)` against `x: int = 5`: the docs permit omission, code is stricter."""
        assert not provable("int", "int | None")
        assert not provable("list[str]", "Optional[list[str]]")

    @pytest.mark.parametrize(
        ("code", "doc"),
        [
            ("JustifyMethod", "str"),  # a Literal alias documented as its base type
            ("TextType", "Text | str"),
            ("SyntaxPosition", "Tuple[int, int]"),
            ("Style", "Segment"),  # either could be an alias
            ("Iterable[Segment]", "Iterable[Segments]"),
            ("Style | str", "str"),
            ("str", "StyleType"),
        ],
    )
    def test_a_name_that_may_be_an_alias_abstains(self, code: str, doc: str) -> None:
        assert not provable(code, doc)

    @pytest.mark.parametrize(
        ("code", "doc"),
        [
            ("Callable[[Any], Any]", "Callable"),
            ("list[int]", "list"),
            ("dict[str, int]", "dict"),
            ("Callable", "Callable[[int], str]"),
        ],
    )
    def test_a_bare_generic_against_its_parameterization_abstains(
        self, code: str, doc: str
    ) -> None:
        assert not provable(code, doc)

    def test_a_shared_unresolved_name_does_not_hide_a_resolved_difference(self) -> None:
        assert provable("Style | int", "Style | str")

    def test_an_unresolved_name_inside_literal_values_is_not_a_name(self) -> None:
        assert provable("Literal['a', 'b']", "int")

    def test_a_dotted_value_inside_literal_is_not_an_unresolved_name(self) -> None:
        assert provable("Literal[Color.RED]", "int")

    @pytest.mark.parametrize(
        ("code", "doc"),
        [("os.PathLike[str]", "str"), ("collections.abc.Iterable[int]", "list[int]")],
    )
    def test_a_dotted_name_outside_typing_may_be_an_alias(self, code: str, doc: str) -> None:
        assert not provable(code, doc)

    def test_an_ellipsis_has_no_name_and_no_head(self) -> None:
        assert provable("Callable[..., int]", "Callable[..., str]")
        assert provable("...", "int")

    def test_names_are_found_inside_parameter_lists_and_nested_unions(self) -> None:
        assert provable("Callable[[], int]", "Callable[[], str]")
        assert provable("list[int | str]", "list[int | bytes]")
        assert not provable("list[int | Style]", "list[int | str]")
        assert not provable("Callable[[Style], int]", "Callable[[str], int]")

    @pytest.mark.parametrize(
        ("code", "doc"),
        [
            ("Literal['r'] | Literal['rb'] | Literal['rt']", "str"),
            ("Literal['left', 'right']", "str"),
            ("str", "Literal['a', 'b']"),
            ("Literal[1, 2]", "int"),
            ("Literal[b'x']", "bytes"),
            ("Literal[True]", "bool"),
            ("Literal['a', 1]", "int | str"),
            ("None | Literal['a']", "None | str"),
        ],
    )
    def test_a_literal_documented_as_its_value_type_abstains(self, code: str, doc: str) -> None:
        """A correct, looser doc: `Literal['a', 'b']` is a `str`."""
        assert not provable(code, doc)

    @pytest.mark.parametrize(
        ("code", "doc"),
        [
            ("Literal['a', 'b']", "int"),
            ("Literal[1, 2]", "str"),
            ("Literal['a', 1]", "str"),  # the int values are not covered
            ("Literal['a'] | int", "str"),  # a second member the docs do not mention
            ("Literal['a']", "Literal['b']"),
            ("Literal[Color.RED]", "str"),  # a value of unknown type
            ("Literal['a', None]", "str"),  # a None value is not a str
            ("Literal[1.5]", "int"),  # a value of a type this rule does not read
        ],
    )
    def test_a_literal_against_a_type_that_does_not_cover_it_is_still_reported(
        self, code: str, doc: str
    ) -> None:
        assert provable(code, doc)

    def test_text_that_is_not_a_type_abstains(self) -> None:
        assert not typecompare.is_provable_difference("the next release", "int")


class TestDocsThatAreLooserThanTheCode:
    """Documenting a supertype is less specific, not wrong (ADR-0007 Amendment 5 C)."""

    @pytest.mark.parametrize(
        ("code", "doc"),
        [
            ("Any", "object"),
            ("object", "Any"),
            ("object", "Any | None"),
            ("Hashable", "object"),
            ("Hashable", "None | object"),
            ("list[str]", "Sequence[str]"),
            ("list", "Sequence"),
            ("tuple[int, ...]", "Sequence[int]"),
            ("dict[str, int]", "Mapping[str, int]"),
            ("set[int]", "AbstractSet[int]"),
            ("list[int]", "Iterable[int]"),
            ("Sequence[int]", "Iterable[int]"),
            ("int", "float"),
            ("bool", "int"),
            ("int", "object"),
            ("str", "Any"),
            ("list[int] | tuple[int, ...]", "Sequence[int]"),
        ],
    )
    def test_a_supertype_in_the_docs_abstains(self, code: str, doc: str) -> None:
        assert not provable(code, doc)

    @pytest.mark.parametrize(
        ("code", "doc"),
        [
            ("list[str]", "Sequence[int]"),  # a supertype, but of something else
            ("list[str]", "Iterable[bytes]"),
            ("int", "Sequence[int]"),  # not a supertype of int
            ("str", "Mapping"),
            ("list[str]", "dict[str, int]"),
            ("Mapping[str, None | str]", "dict[str, str]"),  # narrower, but the arguments differ
        ],
    )
    def test_docs_that_are_unrelated_are_still_reported(self, code: str, doc: str) -> None:
        assert provable(code, doc)

    def test_docs_covering_only_part_of_a_union_in_the_code_are_still_reported(self) -> None:
        assert provable("list[int] | int", "Sequence[int]")
        assert provable("list[int] | str", "Sequence[bytes]")

    def test_looser_docs_that_omit_none_the_code_allows_are_still_reported(self) -> None:
        """PRD §14 #10 still holds: `Sequence[str]` says nothing about None."""
        assert provable("list[str] | None", "Sequence[str]")

    def test_a_top_type_in_the_docs_already_covers_none(self) -> None:
        assert not provable("str | None", "object")
        assert not provable("str | None", "Any")


class TestDocsThatAreNarrowerThanTheCode:
    """ADR-0007 Amendment 7 A: documenting a subtype is less than the code accepts, not wrong."""

    @pytest.mark.parametrize(
        ("code", "doc"),
        [
            ("Mapping[Any, Any]", "dict"),
            ("Mapping[Any, Any] | None", "None | dict"),
            ("None | Sequence[Hashable]", "None | list"),
            ("Iterable[float] | None", "None | tuple"),
            ("Sequence[Hashable]", "list"),
            ("Iterable[int]", "list[int]"),
            ("Hashable", "str"),
            ("float", "int"),
            ("Mapping[str, int]", "dict[str, int]"),
            ("MutableMapping[str, object]", "dict"),
            ("Mapping[Any, bool] | bool", "bool"),  # the docs name only part of the union
            ("Any | bytes | str", "str"),
            ("Any", "int"),  # a top type in the code accepts anything the docs name
            ("object", "list[str]"),
            ("Mapping[Any, Any] | Sequence[int]", "dict | list"),
        ],
    )
    def test_docs_naming_a_subtype_or_part_of_the_union_abstain(self, code: str, doc: str) -> None:
        assert not provable(code, doc)

    def test_docs_that_name_a_member_the_code_does_not_accept_are_still_reported(self) -> None:
        assert provable("Mapping[Any, Any]", "dict | list")
        assert provable("int", "str")
        assert provable("list[int] | int", "Sequence[int]")

    def test_narrower_docs_that_omit_a_none_the_code_allows_are_still_reported(self) -> None:
        """PRD §14 #10 still holds: `dict` says nothing about None."""
        assert provable("Mapping[Any, Any] | None", "dict")
        assert provable("None | Sequence[int]", "list")


class TestNoneOfASentinelParameter:
    """ADR-0007 Amendment 7 B: where None is only the sentinel, the docs need not name it."""

    def test_docs_that_omit_none_are_reported_without_a_sentinel(self) -> None:
        assert typecompare.is_provable_difference(canon("bool | None"), canon("bool"))

    def test_but_not_where_none_is_the_sentinel(self) -> None:
        assert not typecompare.is_provable_difference(
            canon("bool | None"), canon("bool"), none_is_sentinel=True
        )

    def test_a_real_difference_is_still_reported_beside_a_sentinel(self) -> None:
        assert typecompare.is_provable_difference(
            canon("int | None"), canon("str"), none_is_sentinel=True
        )

    def test_narrower_docs_and_a_sentinel_together_abstain(self) -> None:
        assert not typecompare.is_provable_difference(
            canon("Mapping[Any, Any] | None"), canon("dict"), none_is_sentinel=True
        )

    def test_the_flag_reaches_the_several_claims_rule(self) -> None:
        code = canon("bool | None")
        assert typecompare.should_abstain(code, ["bool"], none_is_sentinel=True)
        assert not typecompare.should_abstain(code, ["bool"])
        assert not typecompare.should_abstain(code, ["str"], none_is_sentinel=True)


class TestSentinelDefaults:
    """A code default of None is a sentinel: the docs' effective default is not provably wrong."""

    def test_a_documented_concrete_default_behind_a_none_sentinel_abstains(self) -> None:
        assert typecompare.should_abstain_default("None", ["'numexpr'"])
        assert typecompare.should_abstain_default("None", ["True", "0"])

    def test_agreement_does_not_abstain(self) -> None:
        assert not typecompare.should_abstain_default("None", ["None"])
        assert not typecompare.should_abstain_default("30", ["30"])

    def test_a_concrete_code_default_against_a_different_one_is_reported(self) -> None:
        assert not typecompare.should_abstain_default("0", ["None"])
        assert not typecompare.should_abstain_default("30", ["60"])

    def test_no_documentation_means_nothing_to_abstain_about(self) -> None:
        assert not typecompare.should_abstain_default("None", [])

    def test_only_the_default_slots_are_defaults(self) -> None:
        assert typecompare.is_default_aspect("param.x.default")
        assert not typecompare.is_default_aspect("param.x.type")
        assert not typecompare.is_default_aspect("returns.type")
        assert not typecompare.is_default_aspect("param.x.exists")


class TestAbstentionAcrossSeveralDocClaims:
    def test_nothing_to_compare_never_abstains(self) -> None:
        assert not typecompare.should_abstain("int", [])

    def test_a_doc_claim_that_agrees_does_not_abstain(self) -> None:
        assert not typecompare.should_abstain("int", ["int"])

    def test_a_provable_difference_does_not_abstain(self) -> None:
        assert not typecompare.should_abstain("int", ["str"])

    def test_only_unprovable_differences_abstain(self) -> None:
        assert typecompare.should_abstain("JustifyMethod", ["str"])

    def test_an_agreeing_claim_does_not_rescue_an_unprovable_one(self) -> None:
        """Projecting would open a dispute against the claim we cannot prove wrong."""
        assert typecompare.should_abstain("JustifyMethod", ["JustifyMethod", "str"])

    def test_one_provable_difference_among_unprovable_ones_still_reports(self) -> None:
        assert not typecompare.should_abstain("JustifyMethod", ["str", "JustifyMethod | int"])


class TestWhichSlotsHoldTypes:
    @pytest.mark.parametrize("aspect", ["returns.type", "param.timeout.type", "param.a.b.type"])
    def test_type_slots(self, aspect: str) -> None:
        assert typecompare.is_type_aspect(aspect)

    @pytest.mark.parametrize(
        "aspect", ["param.timeout.default", "param.x.exists", "exists", "raises.ValueError", "type"]
    )
    def test_other_slots(self, aspect: str) -> None:
        assert not typecompare.is_type_aspect(aspect)
