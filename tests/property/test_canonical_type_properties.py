"""Properties of the canonical type form (ADR-0007 Amendment 3).

The form must make representation irrelevant without ever making two genuinely different
types equal, or precision is bought by going blind.
"""

from __future__ import annotations

import itertools

from hypothesis import given
from hypothesis import strategies as st

from plumbline.domain import canonical

ATOMS = ["int", "str", "bytes", "float", "bool", "Style", "Segment"]


def spell(members: list[str], *, quoted: bool, wrapper: str) -> str:
    """The same set of types, written in one of several equivalent ways."""
    shown = [f"'{m}'" if quoted else m for m in members]
    if wrapper == "pipe":
        return " | ".join(shown)
    if wrapper == "pipe_none":
        return " | ".join([*shown, "None"])
    if wrapper == "union":
        return f"Union[{', '.join(shown)}]"
    return f"Optional[Union[{', '.join(shown)}]]" if len(shown) > 1 else f"Optional[{shown[0]}]"


PLAIN = st.sampled_from(["pipe", "union"])  # ways of writing a type that cannot be None
NULLABLE = st.sampled_from(["pipe_none", "optional"])  # ways of writing the same plus None
writing = st.one_of(PLAIN, NULLABLE)


def denotes(members: list[str], wrapper: str) -> frozenset[str]:
    """The set of types a way of writing stands for, ``None`` included."""
    return frozenset([*members, "None"] if wrapper in ("pipe_none", "optional") else members)


@given(
    st.lists(st.sampled_from(ATOMS), min_size=1, max_size=4, unique=True),
    st.randoms(use_true_random=False),
    st.data(),
    st.booleans(),
    st.booleans(),
)
def test_every_way_of_writing_the_same_types_is_one_string(
    members: list[str], rng: object, data: st.DataObject, q1: bool, q2: bool
) -> None:
    pool = data.draw(st.sampled_from([PLAIN, NULLABLE]))  # both spellings agree on None
    first, second = data.draw(pool), data.draw(pool)
    shuffled = list(members)
    rng.shuffle(shuffled)  # type: ignore[attr-defined]
    one = canonical.canonical_type_annotation(spell(members, quoted=q1, wrapper=first))
    other = canonical.canonical_type_annotation(spell(shuffled, quoted=q2, wrapper=second))
    assert one == other


@given(
    st.lists(st.sampled_from(ATOMS), min_size=1, max_size=3, unique=True),
    st.lists(st.sampled_from(ATOMS), min_size=1, max_size=3, unique=True),
    writing,
    writing,
)
def test_different_sets_of_types_are_never_made_equal(
    left: list[str], right: list[str], first: str, second: str
) -> None:
    """Including `None`: `int` and `int | None` are different types (PRD §14 #10)."""
    same = denotes(left, first) == denotes(right, second)
    one = canonical.canonical_type_annotation(spell(left, quoted=False, wrapper=first))
    other = canonical.canonical_type_annotation(spell(right, quoted=False, wrapper=second))
    assert (one == other) == same


@given(
    st.lists(st.sampled_from(ATOMS), min_size=1, max_size=4, unique=True),
    writing,
    st.sampled_from(["{}", "list[{}]", "Dict[str, {}]", "Iterable['{}']", "Callable[[{}], int]"]),
)
def test_the_form_is_a_fixed_point_at_any_depth(
    members: list[str], wrapper: str, shape: str
) -> None:
    text = shape.format(spell(members, quoted=False, wrapper=wrapper))
    once = canonical.canonical_type_annotation(text)
    assert canonical.canonical_type_annotation(once) == once


def test_the_atoms_really_are_distinct_after_canonicalization() -> None:
    forms = {canonical.canonical_type_annotation(a) for a in ATOMS}
    assert len(forms) == len(ATOMS)
    assert all(a != b for a, b in itertools.combinations(forms, 2))
