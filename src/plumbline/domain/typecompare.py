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


def _split_none(members: list[ast.expr]) -> tuple[set[str], bool]:
    """The non-``None`` members as text, and whether ``None`` was among them."""
    texts = {ast.unparse(m) for m in members}
    has_none = "None" in texts
    return (texts - {"None"}) or {"None"}, has_none


def is_provable_difference(code_type: str, doc_type: str) -> bool:
    """Whether the docs' type provably disagrees with the code's. Both are canonical.

    * Equal types do not differ.
    * If they differ only in ``None``: the docs omitting it where the code allows it is a
      difference (PRD §14 #10); the docs allowing it where the code does not is not (a
      documented ``optional`` on a parameter with a default).
    * Otherwise only the members that differ count. If any of them mentions a name that
      is not resolved, or a bare generic stands against its own parameterization, the
      difference is not provable. If they are made only of resolved names it is.
    """
    if code_type == doc_type:
        return False
    code, doc = _parse(code_type), _parse(doc_type)
    if code is None or doc is None:
        return False
    code_rest, code_none = _split_none(_members(code))
    doc_rest, doc_none = _split_none(_members(doc))
    if code_rest == doc_rest:
        return code_none and not doc_none
    only_code = [m for m in _members(code) if ast.unparse(m) in code_rest - doc_rest]
    only_doc = [m for m in _members(doc) if ast.unparse(m) in doc_rest - code_rest]
    if any(not (_names(m) <= _RESOLVED) for m in [*only_code, *only_doc]):
        return False
    code_heads = {h for m in only_code if (h := _head(m))}
    doc_heads = {h for m in only_doc if (h := _head(m))}
    # `Callable` against `Callable[[int], str]`: the docs left the parameters out.
    return all((name, not parameterized) not in doc_heads for name, parameterized in code_heads)


def should_abstain(code_type: str, doc_types: Collection[str]) -> bool:
    """Whether the projector must not state the code's type for a slot.

    True when some doc claim differs from the code but no claim differs *provably*: stating
    the code's type would open a dispute that cannot be shown to be real. A doc claim that
    agrees does not rescue one that cannot be proven wrong, because the dispute would still
    flag every member.
    """
    differing = [d for d in doc_types if d != code_type]
    return bool(differing) and not any(is_provable_difference(code_type, d) for d in differing)
