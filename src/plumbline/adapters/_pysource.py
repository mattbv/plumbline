"""Python-source helpers shared by the code importer and the docstring importer.

Both importers must agree, symbol for symbol, on *what a symbol is*: how a path
becomes a module name, which names are private, which definitions are duplicated
(and so ambiguous), and what a canonical annotation looks like. Keeping one
implementation is what makes a docstring claim land on the same ``Fact`` key as the
code fact it describes. Pure and I/O free.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from plumbline.domain import canonical

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
TYPING_MODULES = ("typing.", "typing_extensions.")


def is_private(name: str) -> bool:
    """Single/double-underscore names are private; dunders like ``__init__`` are not."""
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def module_name(path: str) -> str | None:
    """Dotted module name for a source path, or ``None`` if it is not Python source.

    Everything up to and including the first ``src`` directory is dropped
    (src layout); otherwise the path is taken as-is (flat layout).
    """
    if not path.endswith(".py"):
        return None
    parts = path.removesuffix(".py").split("/")
    if "src" in parts[:-1]:
        parts = parts[parts.index("src") + 1 :]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts or not all(part.isidentifier() for part in parts):
        return None
    return ".".join(parts)


def dotted(node: ast.expr) -> str | None:
    """``a.b.c`` for a pure Name/Attribute chain, else ``None``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return None if base is None else f"{base}.{node.attr}"
    return None


class NormalizeAnnotation(ast.NodeTransformer):
    """Rewrite ``Optional[X]`` / ``Union[A, B]`` to PEP 604 form and drop ``typing.``."""

    def visit_Subscript(self, node: ast.Subscript) -> ast.expr:
        """Rewrite ``Optional[X]`` and ``Union[...]`` subscripts to PEP 604 unions."""
        self.generic_visit(node)
        name = dotted(node.value) or ""
        short = name.rsplit(".", 1)[-1]
        if short == "Optional":
            return ast.BinOp(left=node.slice, op=ast.BitOr(), right=ast.Constant(value=None))
        if short == "Union" and isinstance(node.slice, ast.Tuple) and node.slice.elts:
            result = node.slice.elts[0]
            for member in node.slice.elts[1:]:
                result = ast.BinOp(left=result, op=ast.BitOr(), right=member)
            return result
        return node


def annotation(node: ast.expr) -> str:
    """Canonical text of an annotation expression."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return canonical.canonical_type_annotation(node.value)  # quoted forward reference
    tree = NormalizeAnnotation().visit(ast.fix_missing_locations(node))
    text = ast.unparse(tree)
    for prefix in TYPING_MODULES:
        text = text.replace(prefix, "")
    return canonical.canonical_type_annotation(text)


@dataclass(frozen=True, slots=True)
class Definition:
    """One function, method, or class found in a module."""

    qualname: str
    node: FunctionNode | ast.ClassDef
    in_class: bool


@dataclass(slots=True)
class Walker:
    """Collects definitions, descending through ``if``/``try``/``with`` and class bodies."""

    module: str
    found: list[Definition] = field(default_factory=list)

    def walk(self, body: list[ast.stmt], prefix: str, in_class: bool) -> None:
        """Collect definitions from ``body``, recursing into compound statements and classes."""
        for stmt in body:
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                if any((dotted(d) or "").endswith("overload") for d in stmt.decorator_list):
                    continue  # typing stubs, not definitions
                self.found.append(Definition(f"{prefix}{stmt.name}", stmt, in_class))
            elif isinstance(stmt, ast.ClassDef):
                self.found.append(Definition(f"{prefix}{stmt.name}", stmt, in_class))
                self.walk(stmt.body, f"{prefix}{stmt.name}.", in_class=True)
            elif isinstance(stmt, ast.If | ast.With | ast.AsyncWith | ast.For | ast.While):
                self.walk(stmt.body, prefix, in_class)
                self.walk(stmt.orelse if hasattr(stmt, "orelse") else [], prefix, in_class)
            elif isinstance(stmt, ast.Try):
                for block in (stmt.body, stmt.orelse, stmt.finalbody):
                    self.walk(block, prefix, in_class)
                for handler in stmt.handlers:
                    self.walk(handler.body, prefix, in_class)


def scope_nodes(body: Iterable[ast.AST], *, into_classes: bool = False) -> Iterator[ast.AST]:
    """Nodes that execute *in this namespace*.

    Yields definitions themselves (and what runs at definition time: decorators,
    defaults, bases) but never descends into function, lambda, or comprehension
    bodies. A nested class body is entered only with ``into_classes`` -- it runs
    at import time, but binds names in the *class*, not in this namespace.
    """
    stack = list(body)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            stack.extend(node.decorator_list)
            stack.extend(node.args.defaults)
            stack.extend(d for d in node.args.kw_defaults if d is not None)
        elif isinstance(node, ast.ClassDef):
            stack.extend(node.decorator_list)
            stack.extend(node.bases)
            stack.extend(k.value for k in node.keywords)
            if into_classes:
                stack.extend(node.body)
        elif not isinstance(
            node, ast.Lambda | ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
        ):
            stack.extend(ast.iter_child_nodes(node))


def bound_names(body: Iterable[ast.AST]) -> dict[str, int]:
    """Names bound in this namespace by something other than ``def``/``class``, with first line."""
    found: dict[str, int] = {}

    def bind(name: str, line: int) -> None:
        """Record the first line on which ``name`` is bound."""
        found[name] = min(line, found.get(name, line))

    for node in scope_nodes(body):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bind(node.id, node.lineno)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bind(alias.asname or alias.name.split(".")[0], node.lineno)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    bind(alias.asname or alias.name, node.lineno)
        elif (isinstance(node, ast.ExceptHandler) and node.name) or (
            isinstance(node, ast.MatchAs | ast.MatchStar) and node.name
        ):
            bind(node.name, node.lineno)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            bind(node.rest, node.lineno)
    return found


def annotation_from_text(text: str) -> str | None:
    """Canonical form of a type written as text (e.g. in a docstring), or ``None``.

    ``None`` means "not a type expression I can be sure of": prose, a sentence, or
    anything that does not parse as a plain annotation. Callers abstain on it.
    """
    stripped = text.strip().strip("`")
    if not stripped:
        return None
    try:
        tree = ast.parse(stripped, mode="eval").body
    except (SyntaxError, ValueError, RecursionError):
        return None
    if not isinstance(tree, ast.Name | ast.Attribute | ast.Subscript | ast.BinOp | ast.Constant):
        return None
    if isinstance(tree, ast.Constant) and tree.value is not None:
        return None  # a bare number or string is not a type
    if not _is_type_expression(tree):
        return None
    return annotation(tree)


_TYPE_NODES = (
    ast.Name, ast.Attribute, ast.Subscript, ast.Tuple, ast.List, ast.Constant,
    ast.BinOp, ast.BitOr, ast.Load,
)  # fmt: skip


def _is_type_expression(node: ast.expr) -> bool:
    """Whether ``node`` is made only of what a type annotation is made of.

    Names, dotted names, subscripts, ``|`` unions, lists and tuples of those, and constants
    (``None``, ``...``, forward-reference strings, ``Literal`` values). Anything else, such as
    ``array-like`` (a subtraction), ``shape (n,)`` (a call) or a conditional expression, is prose
    that happens to parse. A whitelist, so a kind of node nobody thought of is refused.
    """
    for child in ast.walk(node):
        if not isinstance(child, _TYPE_NODES):
            return False
        if isinstance(child, ast.BinOp) and not isinstance(child.op, ast.BitOr):
            return False
    return True
