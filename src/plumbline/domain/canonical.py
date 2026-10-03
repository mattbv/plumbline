"""Canonicalization: the product's precision engine (PRD §7.4).

Drift detection is exact-equality comparison on `Fact.value` -- so two
sources that mean the same thing must produce the *same string*, or every
canonicalization gap becomes a false-positive contradiction (Risk R1 in the
PRD). Each function here is pure, deterministic, and versioned via
`CANONICALIZER_VERSION`: bumping it is a visible, auditable event that
should trigger a re-projection pass (ING-5), never a silent behavior change.
"""

from __future__ import annotations

import ast
import json
import math
import re
from collections.abc import Sequence

CANONICALIZER_VERSION = "2"

_WHITESPACE = re.compile(r"\s+")


def canonical_bool(value: bool) -> str:
    """Canonical form of a boolean aspect value: the literal "true"/"false"."""
    return "true" if value else "false"


def canonical_param_names(names: Sequence[str]) -> str:
    """Canonical form of an ordered parameter name list (`param_names`, PRD §7.4).

    Compact JSON in declaration order. The caller excludes `self`/`cls` and
    renders `*args` / `**kwargs` as `*name` / `**name`; this function only
    fixes the *serialization*, so every source produces the same string.
    """
    return json.dumps(list(names), separators=(",", ":"))


def canonical_literal(value: str) -> str | None:
    """Canonical form of a Python literal default (PRD's `param.<p>.default`).

    Args:
        value: Source text of the default expression, e.g. "30" or "'utf-8'".

    Returns:
        `repr()` of the parsed literal, or `None` if the projector should
        abstain -- the expression isn't a literal `ast.literal_eval` can
        evaluate (e.g. it references another name), so no canonical
        projection can be asserted at all (never guess).
    """
    try:
        parsed = ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return None
    if isinstance(parsed, float) and _is_whole_number(parsed):
        return repr(int(parsed))  # `100` and `100.0` are the same default
    return repr(parsed)


def _is_whole_number(value: float) -> bool:
    """Whether a float is finite, integer-valued, and small enough to be written exactly."""
    return math.isfinite(value) and value == int(value) and abs(value) < _MAX_EXACT_INT


# The builtin generics, which typing spells with a capital (ADR-0007 Amendment 3, A).
_BUILTIN_GENERICS = {
    "List": "list",
    "Dict": "dict",
    "Tuple": "tuple",
    "Set": "set",
    "FrozenSet": "frozenset",
    "Type": "type",
}
_TYPING_MODULES = frozenset({"typing", "typing_extensions"})
_VERBATIM = frozenset({"Literal", "Annotated"})  # their arguments are values, not types
_MAX_EXACT_INT = 10**15


def canonical_type_annotation(annotation: str) -> str:
    """Canonical form of a type annotation string (ADR-0007 Amendment 3).

    Two spellings of the same type must produce the same string, because drift detection
    compares strings. The form removes quotation marks at any depth, drops a ``typing.``
    qualifier, spells the builtin generics in lower case, rewrites ``Optional`` and ``Union``
    as unions, and orders and de-duplicates the members. ``None`` is a member like any other:
    ``int`` and ``int | None`` are different types (ADR-0007 Amendment 4). The contents of
    ``Literal[...]`` are values and are left as written.

    Text that is not an expression has only its whitespace collapsed.
    """
    collapsed = _WHITESPACE.sub(" ", annotation.strip())
    try:
        tree = ast.parse(collapsed, mode="eval").body
    except (SyntaxError, ValueError, RecursionError):
        return collapsed
    return ast.unparse(_canonical_node(tree))


def _short_name(node: ast.expr) -> str | None:
    """``List`` for ``List`` and for ``typing.List``; ``None`` for anything else."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.attr if node.value.id in _TYPING_MODULES else None
    return None


def _members(node: ast.expr) -> list[ast.expr]:
    """The members of a (possibly nested) ``a | b | c``."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return [*_members(node.left), *_members(node.right)]
    return [node]


def _union(members: list[ast.expr]) -> ast.expr:
    """Canonical union of already-canonical members: flattened, de-duplicated, ordered."""
    flat: dict[str, ast.expr] = {}
    for member in members:
        for part in _members(member):
            flat.setdefault(ast.unparse(part), part)
    ordered = [flat[key] for key in sorted(flat)]
    result = ordered[0]
    for member in ordered[1:]:
        result = ast.BinOp(left=result, op=ast.BitOr(), right=member)
    return result


def _canonical_node(node: ast.expr) -> ast.expr:
    """The canonical form of one annotation expression, recursively."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:  # a quoted forward reference is the type it names
            inner = ast.parse(node.value.strip(), mode="eval").body
        except (SyntaxError, ValueError, RecursionError):
            return node
        return _canonical_node(inner)
    if isinstance(node, ast.Name | ast.Attribute):
        name = _short_name(node)
        if name is None:
            return node
        return ast.Name(id=_BUILTIN_GENERICS.get(name, name), ctx=ast.Load())
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _union([_canonical_node(m) for m in _members(node)])
    if isinstance(node, ast.Subscript):
        return _canonical_subscript(node)
    if isinstance(node, ast.List):
        return ast.List(elts=[_canonical_node(e) for e in node.elts], ctx=ast.Load())
    if isinstance(node, ast.Tuple):
        return ast.Tuple(elts=[_canonical_node(e) for e in node.elts], ctx=ast.Load())
    return node


def _canonical_subscript(node: ast.Subscript) -> ast.expr:
    base = _short_name(node.value)
    if base in _VERBATIM:
        return ast.Subscript(
            value=ast.Name(id=base, ctx=ast.Load()), slice=node.slice, ctx=ast.Load()
        )
    arguments = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    canonical_args = [_canonical_node(a) for a in arguments]
    if base == "Optional":
        return _union([*canonical_args, ast.Constant(value=None)])
    if base == "Union":
        return _union(canonical_args)
    head = _canonical_node(node.value)
    slice_: ast.expr = (
        ast.Tuple(elts=canonical_args, ctx=ast.Load())
        if isinstance(node.slice, ast.Tuple)
        else canonical_args[0]
    )
    return ast.Subscript(value=head, slice=slice_, ctx=ast.Load())


def canonical_version(version: str) -> str | None:
    """Canonical form of a PEP 440-ish version string.

    Returns:
        The trimmed version string, or `None` if it doesn't look like a
        version at all (abstain rather than assert something wrong).
    """
    trimmed = version.strip()
    if not re.match(r"^v?\d+(\.\d+)*([.\-\+][0-9A-Za-z.]+)?$", trimmed):
        return None
    return trimmed.removeprefix("v")
