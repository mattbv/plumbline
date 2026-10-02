"""Properties the docstring importer must hold for *any* docstring (PRD §9.4, ADR-0006).

Docstrings are untrusted text. Whatever one says, the importer must not crash,
must only emit values in canonical form, and must read a stated default back out
exactly.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime

from hypothesis import event, given, settings
from hypothesis import strategies as st

from plumbline.adapters._pysource import annotation_from_text
from plumbline.adapters.docstring_claim_importer import DocstringClaimImporter
from plumbline.application.ports import CommitRef
from plumbline.domain import canonical
from tests.zoo.oracle import resolve_aspect, value_problem

COMMIT = CommitRef("abcdef0123456789abcdef0123456789abcdef01", datetime(2024, 1, 1, tzinfo=UTC), ())

_line = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00\r"),
    max_size=60,
)
_FRAGMENTS = [
    "Args:", "    a (int, optional): Seconds. Defaults to 3.", "    b (list of str): Items.",
    "    *args: Extra.", "Returns:", "    int: The count.", "    result: a label", "Raises:",
    "    KeyError: If missing.", "Parameters", "----------", "a : int, default 5",
    "    Description.", "b : Optional[str]", "Returns", "-------", "bool", "Raises", "------",
    "ValueError", ":param str a: the a", ":type b: int", ":rtype: bool", ":raises KeyError: no",
    ".. deprecated:: 1.2", "    continued description. Default is 'x'.", "",
]  # fmt: skip
_docs = st.lists(st.one_of(st.sampled_from(_FRAGMENTS), _line), max_size=14).map("\n".join)


def _source(doc: str) -> bytes:
    return f"def f(a, b):\n    {doc!r}\n".encode()


@settings(max_examples=400)
@given(_docs)
def test_any_docstring_is_survivable_and_yields_only_canonical_values(doc: str) -> None:
    out = DocstringClaimImporter("o", "r").extract({"src/p/m.py": _source(doc)}, COMMIT)
    event("claims" if out.claims else "no claims")
    for claim in out.claims:
        aspect = resolve_aspect(claim.aspect)
        assert aspect is not None, claim.aspect
        assert value_problem(aspect, claim.raw_value) is None, (claim.aspect, claim.raw_value)
        assert 0.0 < claim.confidence <= 1.0
        assert "[docstring-claim-importer/1]" in claim.rationale


@settings(max_examples=200)
@given(st.binary(max_size=1500))
def test_arbitrary_bytes_never_crash_the_importer(blob: bytes) -> None:
    out = DocstringClaimImporter("o", "r").extract({"src/p/m.py": blob}, COMMIT)
    assert isinstance(out.claims, list)


@given(st.integers(min_value=-10_000, max_value=10_000))
def test_a_stated_integer_default_is_read_back_exactly(n: int) -> None:
    doc = f"Doc.\n\nArgs:\n    a (int): The count. Defaults to {n}.\n"
    out = DocstringClaimImporter("o", "r").extract({"src/p/m.py": _source(doc)}, COMMIT)
    defaults = [c for c in out.claims if c.aspect == "param.a.default"]
    assert [ast.literal_eval(c.raw_value) for c in defaults] == [n]


@given(
    st.sampled_from(
        [
            "int",
            "str",
            "list[int]",
            "dict[str, int]",
            "Optional[int]",
            "int | None",
            "typing.Optional[str]",
        ]
    )
)
def test_canonical_types_are_a_fixed_point(type_text: str) -> None:
    """Reading a canonical type back through the importer's own parser changes nothing."""
    once = annotation_from_text(type_text)
    assert once is not None
    assert annotation_from_text(once) == once == canonical.canonical_type_annotation(once)


@given(st.permutations(["a.py", "b.py", "c.py"]))
def test_extraction_is_independent_of_file_order(order: list[str]) -> None:
    body = b'def f(x):\n    """.. deprecated:: 1"""\n'
    importer = DocstringClaimImporter("o", "r")
    files = {f"src/p/{name}": body for name in order}
    baseline = importer.extract({f"src/p/{n}": body for n in ("a.py", "b.py", "c.py")}, COMMIT)
    assert importer.extract(files, COMMIT) == baseline


def test_the_fragments_really_do_exercise_every_parser() -> None:
    """Guard: the property above is only meaningful if its inputs produce claims.

    The fragments deliberately disagree with each other (``a`` is an ``int`` in one
    style and a ``str`` in another, with defaults 3 and 5; the return type is ``int``
    and ``bool``), so the agreed facts must survive and the disputed ones must not.
    """
    doc = "\n".join(_FRAGMENTS)
    out = DocstringClaimImporter("o", "r").extract({"src/p/m.py": _source(doc)}, COMMIT)
    aspects = {c.aspect for c in out.claims}
    assert {
        "deprecated",
        "param.a.exists",
        "param.b.type",
        "raises.KeyError",
        "raises.ValueError",
    } <= aspects
    assert not aspects & {"param.a.type", "param.a.default", "returns.type"}
