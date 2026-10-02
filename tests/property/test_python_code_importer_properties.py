"""Properties the code importer must hold for *any* input (PRD §9.4, ING-1)."""

from __future__ import annotations

import ast
from datetime import UTC, datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from plumbline.adapters.python_code_importer import PythonCodeImporter
from plumbline.application.ports import CommitRef

COMMIT = CommitRef(
    sha="abcdef0123456789abcdef0123456789abcdef01",
    committed_at=datetime(2024, 1, 1, tzinfo=UTC),
    changed_paths=(),
)

literals = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(),
    lambda inner: st.tuples(inner, inner) | st.lists(inner, max_size=3).map(tuple),
    max_leaves=6,
)


@given(literals)
def test_literal_defaults_round_trip(value: object) -> None:
    """Whatever literal a default is, the emitted canonical value evaluates back to it."""
    source = f"def f(x={value!r}): ...\n".encode()
    claims = PythonCodeImporter("o", "r").extract({"src/p/m.py": source}, COMMIT)
    emitted = {c.aspect: c.raw_value for c in claims if c.symbol_key == "py:p.m.f"}
    assert ast.literal_eval(emitted["param.x.default"]) == value


@given(
    st.dictionaries(
        st.sampled_from("abcdef").map(lambda n: f"src/p/{n}.py"),
        st.sampled_from(["def f(): ...\n", "class C:\n  def m(self, a=1): ...\n"]),
        min_size=1,
    ),
    st.randoms(),
)
def test_extraction_is_independent_of_input_order(files: dict[str, str], rnd: object) -> None:
    encoded = {path: text.encode() for path, text in files.items()}
    shuffled_keys = list(encoded)
    rnd.shuffle(shuffled_keys)  # type: ignore[attr-defined]
    shuffled = {k: encoded[k] for k in shuffled_keys}
    importer = PythonCodeImporter("o", "r")
    assert importer.extract(encoded, COMMIT) == importer.extract(shuffled, COMMIT)


@settings(max_examples=200)
@given(st.binary(max_size=2000))
def test_arbitrary_bytes_never_crash_the_importer(blob: bytes) -> None:
    """Repository content is untrusted: the importer abstains, it never raises."""
    claims = PythonCodeImporter("o", "r").extract({"src/p/m.py": blob}, COMMIT)
    assert isinstance(claims, list)


_names = st.from_regex(r"[a-z][a-z0-9]{0,8}", fullmatch=True).filter(
    lambda n: (
        n
        not in {
            "if",
            "in",
            "is",
            "or",
            "as",
            "del",
            "for",
            "def",
            "not",
            "and",
            "try",
            "with",
            "from",
            "pass",
            "None",
            "True",
            "else",
            "elif",
            "case",
            "type",
            "async",
            "await",
            "class",
            "raise",
            "while",
            "yield",
            "break",
            "match",
            "lambda",
            "global",
            "assert",
            "except",
            "import",
            "return",
            "finally",
            "continue",
            "nonlocal",
        }
    )
)


@given(st.sets(_names, min_size=1, max_size=6))
def test_every_assigned_public_name_is_listed(names: set[str]) -> None:
    """A closed namespace must list every name it binds (ADR-0003)."""
    source = "".join(f"{name} = 1\n" for name in sorted(names)).encode()
    claims = PythonCodeImporter("o", "r").extract({"src/p/m.py": source}, COMMIT)
    listed = {c.symbol_key for c in claims if c.aspect == "exists"}
    assert {f"py:p.m.{n}" for n in names} <= listed
    assert {c.raw_value for c in claims if c.aspect == "namespace_closed"} == {"true"}
