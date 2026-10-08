"""When two canonical types differ provably, and when the tool must stay silent.

Drift detection compares canonical strings (`plumbline.domain.canonical`). Once two types
differ as strings, a finding is only honest if the difference is *provable*: a single-file
analysis cannot see through an alias, so a disagreement that might be an alias in disguise
is not evidence of drift (ADR-0007 Amendments 3 and 4). Pure and deterministic: the set of
names it can resolve is written out here, never read from the running interpreter.
"""

from __future__ import annotations

import ast
from collections.abc import Collection

# Names whose meaning is fixed, so a disagreement involving only these is real.
_RESOLVED = frozenset(
    {
        # builtins
        "int", "float", "str", "bytes", "bool", "complex", "list", "dict", "set", "frozenset",
        "tuple", "type", "object", "bytearray", "memoryview", "range", "slice", "None",
        # typing and collections.abc (the names that survive canonicalization)
        "Any", "Callable", "Iterable", "Iterator", "Sequence", "MutableSequence", "Mapping",
        "MutableMapping", "AbstractSet", "MutableSet", "Collection", "Container", "Generator",
        "Awaitable", "Coroutine", "AsyncIterable", "AsyncIterator", "AsyncGenerator", "Hashable",
        "Sized", "Reversible", "Literal", "NoReturn", "Never", "Self", "LiteralString",
        "Ellipsis", "Final", "ClassVar", "Annotated",
    }
)  # fmt: skip


_TOP = frozenset({"object", "Any"})
"""The top types: documenting one is true of every type, including ``None``."""
_SUPERTYPES: dict[str, frozenset[str]] = {
    "list": frozenset({"Sequence", "MutableSequence", "Collection", "Iterable"}),
    "tuple": frozenset({"Sequence", "Collection", "Iterable", "Hashable"}),
    "str": frozenset({"Sequence", "Collection", "Iterable", "Hashable"}),
    "bytes": frozenset({"Sequence", "Collection", "Iterable", "Hashable"}),
    "dict": frozenset({"Mapping", "MutableMapping", "Collection", "Iterable"}),
    "set": frozenset({"AbstractSet", "MutableSet", "Collection", "Iterable"}),
    "frozenset": frozenset({"AbstractSet", "Collection", "Iterable", "Hashable"}),
    "Sequence": frozenset({"Collection", "Iterable"}),
    "MutableSequence": frozenset({"Sequence", "Collection", "Iterable"}),
    "Mapping": frozenset({"Collection", "Iterable"}),
    "MutableMapping": frozenset({"Mapping", "Collection", "Iterable"}),
    "AbstractSet": frozenset({"Collection", "Iterable"}),
    "MutableSet": frozenset({"AbstractSet", "Collection", "Iterable"}),
    "Collection": frozenset({"Iterable"}),
    "Iterator": frozenset({"Iterable"}),
    "Generator": frozenset({"Iterator", "Iterable"}),
    "int": frozenset({"float", "complex", "Hashable"}),
    "float": frozenset({"complex", "Hashable"}),
    "bool": frozenset({"int", "float", "complex", "Hashable"}),
}
"""Which resolved names are supertypes of which (typing's numeric tower included).
Written out, never read from the interpreter, so the answer cannot vary by Python version."""


def is_default_aspect(aspect: str) -> bool:
    """Whether a slot holds a parameter's default (``param.<p>.default``)."""
    return aspect.startswith("param.") and aspect.endswith(".default")


def should_abstain_default(code_default: str, doc_defaults: Collection[str]) -> bool:
    """Whether the projector must not state the code's default for a slot.

    A code default of ``None`` usually means "computed or unset", so a docs default that
    states the effective value (``engine=None`` documented as ``default 'numexpr'``) is not
    provably wrong (ADR-0007 Amendment 5 D). A concrete code default against a different
    documented one is still a real disagreement, and so is docs saying ``None`` over a value.
    """
    return code_default == "None" and any(d != "None" for d in doc_defaults)


def is_type_aspect(aspect: str) -> bool:
    """Whether a slot holds a type (``param.<p>.type`` or ``returns.type``)."""
    return aspect == "returns.type" or (aspect.startswith("param.") and aspect.endswith(".type"))


def _parse(canonical_type: str) -> ast.expr | None:
    try:
        return ast.parse(canonical_type, mode="eval").body
    except (SyntaxError, ValueError, RecursionError):
        return None


def _members(node: ast.expr) -> list[ast.expr]:
    """The members of a top-level union."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return [*_members(node.left), *_members(node.right)]
    return [node]


def _names(node: ast.expr) -> set[str]:
    """Every name a type mentions, except inside ``Literal[...]`` (those are values)."""
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return {ast.unparse(node)}  # a dotted name is never in the resolved set
    if isinstance(node, ast.Subscript):
        head = _names(node.value)
        if head == {"Literal"}:
            return head
        return head | _names(node.slice)
    if isinstance(node, ast.Tuple | ast.List):
        return set().union(*(_names(e) for e in node.elts)) if node.elts else set()
    if isinstance(node, ast.BinOp):
        return _names(node.left) | _names(node.right)
    return set()


def _head(node: ast.expr) -> tuple[str, bool] | None:
    """``(outer name, is parameterized)`` of a type, or ``None`` if it has no single head."""
    if isinstance(node, ast.Name):
        return node.id, False
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        return node.value.id, True
    return None


_VALUE_TYPES = {str: "str", int: "int", bytes: "bytes", bool: "bool"}


def _literal_value_types(node: ast.expr) -> set[str] | None:
    """The types of the values of a ``Literal[...]``, or ``None`` if it is not one we can read.

    ``Literal['a', 1]`` gives ``{'str', 'int'}``. A value that is not a plain constant
    (``Color.RED``) makes the answer unknown.
    """
    if not (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "Literal"
    ):
        return None
    values = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    types: set[str] = set()
    for value in values:
        if not isinstance(value, ast.Constant) or type(value.value) not in _VALUE_TYPES:
            return None
        types.add(_VALUE_TYPES[type(value.value)])
    return types


def _covered_by(literals: list[ast.expr], others: list[ast.expr]) -> bool:
    """Whether every member is a ``Literal`` whose values are all of types ``others`` name."""
    named = {m.id for m in others if isinstance(m, ast.Name)}
    for member in literals:
        types = _literal_value_types(member)
        if types is None or not types <= named:
            return False
    return bool(literals)


def _args(node: ast.expr) -> str:
    """The type arguments of a parameterized type as text; ``tuple[X, ...]`` counts as ``X``."""
    if not isinstance(node, ast.Subscript):
        return ""
    inner = node.slice
    if (
        isinstance(node.value, ast.Name)
        and node.value.id == "tuple"
        and isinstance(inner, ast.Tuple)
        and len(inner.elts) == 2
        and isinstance(inner.elts[1], ast.Constant)
        and inner.elts[1].value is Ellipsis
    ):
        inner = inner.elts[0]
    return ast.unparse(inner)


def _loosens(doc: ast.expr, code: ast.expr) -> bool:
    """Whether the docs' member is a supertype of the code's (a less specific, true statement)."""
    doc_head, code_head = _head(doc), _head(code)
    if doc_head is None or code_head is None:
        return False
    if doc_head[0] in _TOP:
        return True
    if doc_head[0] != code_head[0] and doc_head[0] not in _SUPERTYPES.get(code_head[0], ()):
        return False
    return not doc_head[1] or _args(doc) == _args(code)


def _loosened_by(code_members: list[ast.expr], doc_members: list[ast.expr]) -> bool:
    """Whether every differing code member is covered by some docs member that is a supertype."""
    return bool(code_members) and all(
        any(_loosens(d, c) for d in doc_members) for c in code_members
    )


def _narrows(code: ast.expr, doc: ast.expr) -> bool:
    """Whether the docs' member is the code's member or a subtype of it.

    Arguments must agree unless either side leaves them out (``dict`` for ``Mapping[Any, Any]``,
    or ``Mapping`` for ``dict[str, int]``); a top type in the code covers every docs member.
    """
    code_head, doc_head = _head(code), _head(doc)
    if code_head is None or doc_head is None:
        return False
    if code_head[0] in _TOP:
        return True
    if code_head[0] != doc_head[0] and code_head[0] not in _SUPERTYPES.get(doc_head[0], ()):
        return False
    return not code_head[1] or not doc_head[1] or _args(code) == _args(doc)


def _narrower(code_members: list[ast.expr], doc_members: list[ast.expr]) -> bool:
    """Whether every member the docs name is, or is a subtype of, a member of the code's type.

    Documenting ``dict`` for ``Mapping[Any, Any]``, or ``bool`` for ``Mapping[Any, bool] |
    bool``, promises less than the code accepts: true, if not complete (ADR-0007 Amendment 7 A).
    ``None`` is set aside by the caller.
    """
    return bool(doc_members) and all(
        any(ast.unparse(c) == ast.unparse(d) or _narrows(c, d) for c in code_members)
        for d in doc_members
    )


def _split_none(members: list[ast.expr]) -> tuple[set[str], bool]:
    """The non-``None`` members as text, and whether ``None`` was among them."""
    texts = {ast.unparse(m) for m in members}
    has_none = "None" in texts
    return (texts - {"None"}) or {"None"}, has_none


def is_provable_difference(
    code_type: str, doc_type: str, *, none_is_sentinel: bool = False
) -> bool:
    """Whether the docs' type provably disagrees with the code's. Both are canonical.

    * Equal types do not differ.
    * If they differ only in ``None``: the docs omitting it where the code allows it is a
      difference (PRD §14 #10); the docs allowing it where the code does not is not (a
      documented ``optional`` on a parameter with a default).
    * Otherwise only the members that differ count. If any of them mentions a name that
      is not resolved, a bare generic stands against its own parameterization, or one side
      is only ``Literal`` values of types the other side names, or the docs name a supertype of
      each differing code member (less specific, not wrong), or every member the docs name is a
      subtype of one the code accepts (narrower, not wrong), the difference is not provable.
      If they are made only of resolved names it is.
    * ``none_is_sentinel``: the code's default for this parameter is ``None`` and the docs state a
      concrete one, so the ``| None`` in the annotation is that sentinel and a docs type that
      omits it is not a difference (ADR-0007 Amendment 7 B).
    """
    if code_type == doc_type:
        return False
    code, doc = _parse(code_type), _parse(doc_type)
    if code is None or doc is None:
        return False
    code_rest, code_none = _split_none(_members(code))
    doc_rest, doc_none = _split_none(_members(doc))
    omits_none = code_none and not doc_none and not none_is_sentinel
    if code_rest == doc_rest:
        return omits_none
    only_code = [m for m in _members(code) if ast.unparse(m) in code_rest - doc_rest]
    only_doc = [m for m in _members(doc) if ast.unparse(m) in doc_rest - code_rest]
    if any(not (_names(m) <= _RESOLVED) for m in [*only_code, *only_doc]):
        return False
    # A `Literal['a', 'b']` is a `str`: documenting it as `str` is looser, not wrong.
    if _covered_by(only_code, only_doc) or _covered_by(only_doc, only_code):
        return False
    if _loosened_by(only_code, only_doc):
        # Less specific, not wrong. A top type already covers None; any other supertype does not
        # say, so docs that omit a None the code allows are still reported (PRD §14 #10).
        covers_none = doc_none or any(_head(m) and _head(m)[0] in _TOP for m in only_doc)  # type: ignore[index]
        return code_none and not covers_none and not none_is_sentinel
    code_members = [m for m in _members(code) if ast.unparse(m) != "None"]
    doc_members = [m for m in _members(doc) if ast.unparse(m) != "None"]
    if _narrower(code_members, doc_members):
        return omits_none  # narrower, not wrong; an omitted None is still PRD §14 #10
    code_heads = {h for m in only_code if (h := _head(m))}
    doc_heads = {h for m in only_doc if (h := _head(m))}
    # `Callable` against `Callable[[int], str]`: the docs left the parameters out.
    return all((name, not parameterized) not in doc_heads for name, parameterized in code_heads)


def should_abstain(
    code_type: str, doc_types: Collection[str], *, none_is_sentinel: bool = False
) -> bool:
    """Whether the projector must not state the code's type for a slot.

    True when some doc claim differs from the code but no claim differs *provably*: stating
    the code's type would open a dispute that cannot be shown to be real. A doc claim that
    agrees does not rescue one that cannot be proven wrong, because the dispute would still
    flag every member.
    """
    differing = [d for d in doc_types if d != code_type]
    return bool(differing) and not any(
        is_provable_difference(code_type, d, none_is_sentinel=none_is_sentinel) for d in differing
    )
