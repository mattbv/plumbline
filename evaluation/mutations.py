"""Precise, syntax-preserving source edits for seeded-drift injection.

Every edit is located with the ``ast`` (positions, not text search) so it touches exactly
the one thing it means to: a default, an annotation, a parameter name, one line of a
docstring. Each function returns ``None`` when it cannot make the edit safely, and the
caller skips that candidate rather than risk an edit that does something else.

Docstring edits are pure string functions over the docstring's value, so they can be
tested without any source file.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Sequence
from dataclasses import dataclass

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True, slots=True)
class Span:
    """A region of source: 1-based lines, 0-based character columns."""

    line: int
    col: int
    end_line: int
    end_col: int


def _char_col(lines: Sequence[str], line: int, byte_col: int) -> int:
    """``ast`` columns are UTF-8 byte offsets; convert one to a character column."""
    return len(lines[line - 1].encode("utf-8")[:byte_col].decode("utf-8", errors="ignore"))


def span_of(source: str, node: ast.AST) -> Span:
    """The source span of ``node``."""
    lines = source.splitlines(keepends=True)
    line, end_line = node.lineno, node.end_lineno  # type: ignore[attr-defined]
    return Span(
        line,
        _char_col(lines, line, node.col_offset),  # type: ignore[attr-defined]
        end_line,
        _char_col(lines, end_line, node.end_col_offset),  # type: ignore[attr-defined]
    )


def replace_span(source: str, span: Span, text: str) -> str:
    """``source`` with ``span`` replaced by ``text``."""
    lines = source.splitlines(keepends=True)
    head = "".join(lines[: span.line - 1]) + lines[span.line - 1][: span.col]
    tail = lines[span.end_line - 1][span.end_col :] + "".join(lines[span.end_line :])
    return head + text + tail


def find_function(tree: ast.Module, qualname: str) -> FunctionNode | None:
    """The one function or method named ``qualname`` (relative to the module), else ``None``."""
    found: list[FunctionNode] = []

    def walk(body: list[ast.stmt], prefix: str) -> None:
        for stmt in body:
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                if f"{prefix}{stmt.name}" == qualname:
                    found.append(stmt)
            elif isinstance(stmt, ast.ClassDef):
                walk(stmt.body, f"{prefix}{stmt.name}.")
            elif isinstance(stmt, ast.If | ast.With | ast.AsyncWith | ast.For | ast.While):
                walk(stmt.body, prefix)
                walk(getattr(stmt, "orelse", []), prefix)
            elif isinstance(stmt, ast.Try):
                for block in (stmt.body, stmt.orelse, stmt.finalbody):
                    walk(block, prefix)
                for handler in stmt.handlers:
                    walk(handler.body, prefix)

    walk(tree.body, "")
    return found[0] if len(found) == 1 else None


def _parse(source: str) -> ast.Module | None:
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def _checked(original: str, edited: str) -> str | None:
    """``edited`` if it still parses and actually changed, else ``None``."""
    return edited if edited != original and _parse(edited) is not None else None


def _arg(func: FunctionNode, name: str) -> ast.arg | None:
    every = [*func.args.posonlyargs, *func.args.args, *func.args.kwonlyargs]
    return next((a for a in every if a.arg == name), None)


def _default(func: FunctionNode, name: str) -> ast.expr | None:
    positional = [*func.args.posonlyargs, *func.args.args]
    for arg, default in zip(reversed(positional), reversed(func.args.defaults), strict=False):
        if arg.arg == name:
            return default
    for arg, kw_default in zip(func.args.kwonlyargs, func.args.kw_defaults, strict=True):
        if arg.arg == name:
            return kw_default
    return None


def has_var_keyword(func: FunctionNode) -> bool:
    """Whether the signature has ``**kwargs`` (which makes a missing keyword unprovable)."""
    return func.args.kwarg is not None


def set_default(source: str, qualname: str, param: str, new_text: str) -> str | None:
    """Replace ``param``'s default expression with ``new_text``."""
    tree = _parse(source)
    func = None if tree is None else find_function(tree, qualname)
    default = None if func is None else _default(func, param)
    if default is None:
        return None
    return _checked(source, replace_span(source, span_of(source, default), new_text))


def set_param_annotation(source: str, qualname: str, param: str, new_text: str) -> str | None:
    """Replace ``param``'s existing annotation with ``new_text``."""
    tree = _parse(source)
    func = None if tree is None else find_function(tree, qualname)
    arg = None if func is None else _arg(func, param)
    if arg is None or arg.annotation is None:
        return None
    return _checked(source, replace_span(source, span_of(source, arg.annotation), new_text))


def set_return_annotation(source: str, qualname: str, new_text: str) -> str | None:
    """Replace the function's existing return annotation with ``new_text``."""
    tree = _parse(source)
    func = None if tree is None else find_function(tree, qualname)
    if func is None or func.returns is None:
        return None
    return _checked(source, replace_span(source, span_of(source, func.returns), new_text))


def rename_param(source: str, qualname: str, param: str, new_name: str) -> str | None:
    """Rename ``param`` in the signature only (the body keeps its old references)."""
    tree = _parse(source)
    func = None if tree is None else find_function(tree, qualname)
    arg = None if func is None else _arg(func, param)
    if arg is None:
        return None
    start = span_of(source, arg)
    name_span = Span(start.line, start.col, start.line, start.col + len(param))
    return _checked(source, replace_span(source, name_span, new_name))


def _body_indent(func: FunctionNode, source: str) -> str:
    lines = source.splitlines()
    first = func.body[0]
    return lines[first.lineno - 1][: first.col_offset]


def _after_docstring_line(func: FunctionNode) -> int:
    """The 1-based line after which a new statement can be inserted without splitting anything."""
    first = func.body[0]
    is_doc = (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    )
    return (first.end_lineno or first.lineno) if is_doc else func.lineno


def insert_after_docstring(source: str, qualname: str, text: str) -> str | None:
    """Insert one line (``text``, without indentation) at the start of the function body."""
    tree = _parse(source)
    func = None if tree is None else find_function(tree, qualname)
    if func is None or (func.body[0].lineno == func.lineno):
        return None  # a one-line function: nowhere safe to insert
    lines = source.splitlines(keepends=True)
    at = _after_docstring_line(func)
    indent = _body_indent(func, source)
    lines.insert(at, f"{indent}{text}\n")
    return _checked(source, "".join(lines))


def _own_nodes(func: FunctionNode) -> list[ast.AST]:
    """Every node that executes as part of ``func`` itself (not in nested functions or classes)."""
    found: list[ast.AST] = []
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        found.append(node)
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
            stack.extend(ast.iter_child_nodes(node))
    return found


def replace_raise_with_pass(source: str, qualname: str, exception: str) -> str | None:
    """Replace the first ``raise <exception>...`` directly in the function with ``pass``."""
    tree = _parse(source)
    func = None if tree is None else find_function(tree, qualname)
    if func is None:
        return None
    for node in sorted(
        _own_nodes(func), key=lambda n: (getattr(n, "lineno", 0), getattr(n, "col_offset", 0))
    ):
        if isinstance(node, ast.Raise) and node.exc is not None:
            target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            if ast.unparse(target).rsplit(".", 1)[-1] == exception:
                return _checked(source, replace_span(source, span_of(source, node), "pass"))
    return None


def append_function(source: str, name: str) -> str | None:
    """Append a new, undocumented, public function at the end of the module."""
    return _checked(source, source.rstrip("\n") + f"\n\n\ndef {name}():\n    return None\n")


# --- docstrings ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DocstringSite:
    """Where a function's docstring is, and the text it contains."""

    span: Span
    value: str
    indent: str


def docstring_site(source: str, qualname: str) -> DocstringSite | None:
    """The function's plain ``\"\"\"`` docstring, or ``None`` if it has none or is unusual."""
    tree = _parse(source)
    func = None if tree is None else find_function(tree, qualname)
    if func is None or not func.body:
        return None
    first = func.body[0]
    if not (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return None
    node = first.value
    span = span_of(source, node)
    lines = source.splitlines(keepends=True)
    literal = "".join(lines[span.line - 1 : span.end_line])
    segment_start = lines[span.line - 1][span.col :]
    if not segment_start.startswith('"""') or "\\" in literal or "'''" in literal:
        return None  # prefixed, single-quoted, or escape-bearing: too easy to corrupt
    if not isinstance(node.value, str):
        return None
    return DocstringSite(span, node.value, lines[first.lineno - 1][: first.col_offset])


def replace_docstring(source: str, qualname: str, new_value: str) -> str | None:
    """Rewrite the function's docstring so its value becomes ``new_value``."""
    site = docstring_site(source, qualname)
    if site is None or '"""' in new_value or "\\" in new_value:
        return None
    return _checked(source, replace_span(source, site.span, f'"""{new_value}"""'))


_DEFAULT = re.compile(
    r"(\bdefaults?\b\s*(?:to|is|=|:)?\s*)(`[^`]+`|'[^']*'|\"[^\"]*\"|[^\s,;)]+)", re.IGNORECASE
)


def _entry_lines(lines: list[str], param: str) -> tuple[int, int] | None:
    """The line range of ``param``'s entry in a Google ``Args:`` section."""
    for i, line in enumerate(lines):
        if re.match(rf"^\s+{re.escape(param)}\s*(\(.*\))?\s*:", line):
            indent = len(line) - len(line.lstrip())
            end = i + 1
            while end < len(lines) and (
                not lines[end].strip() or len(lines[end]) - len(lines[end].lstrip()) > indent
            ):
                end += 1
            return i, end
    return None


def docstring_set_default(value: str, param: str, new_text: str) -> str | None:
    """Change the default the docstring states for ``param`` (prose such as "Defaults to 30")."""
    lines = value.split("\n")
    entry = _entry_lines(lines, param)
    if entry is None:
        return None
    for i in range(*entry):
        match = _DEFAULT.search(lines[i])
        if match:
            token = match[2]
            core = token.rstrip(".,;)")  # keep the sentence's own punctuation
            end = match.start(2) + len(core)
            lines[i] = lines[i][: match.start(2)] + new_text + lines[i][end:]
            return "\n".join(lines)
    return None


def docstring_set_param_type(value: str, param: str, new_type: str) -> str | None:
    """Change the type in ``param (type): ...``."""
    pattern = re.compile(rf"^(\s+{re.escape(param)}\s*\()([^)]*)(\)\s*:)", re.MULTILINE)
    match = pattern.search(value)
    if match is None:
        return None
    parts = match[2].split(",", 1)
    rest = "," + parts[1] if len(parts) > 1 else ""
    return value[: match.start(2)] + new_type + rest + value[match.end(2) :]


def docstring_set_return_type(value: str, new_type: str) -> str | None:
    """Change the type on the first line under ``Returns:`` (``type: description``)."""
    lines = value.split("\n")
    for i, line in enumerate(lines):
        if re.match(r"^\s*Returns?\s*:\s*$", line) and i + 1 < len(lines):
            match = re.match(r"^(\s+)([^:\s][^:]*?)(\s*:\s+.*)$", lines[i + 1])
            if match:
                lines[i + 1] = match[1] + new_type + match[3]
                return "\n".join(lines)
    return None


def docstring_add_param(value: str, name: str, type_text: str) -> str | None:
    """Add an entry for a parameter that does not exist, at the end of the ``Args:`` section."""
    lines = value.split("\n")
    for i, line in enumerate(lines):
        if re.match(r"^\s*(Args|Arguments|Parameters)\s*:\s*$", line):
            header = len(line) - len(line.lstrip())
            if i + 1 >= len(lines):
                return None
            entry_indent = len(lines[i + 1]) - len(lines[i + 1].lstrip())
            if entry_indent <= header:
                return None
            end = i + 1
            while end < len(lines) and (
                not lines[end].strip() or len(lines[end]) - len(lines[end].lstrip()) > header
            ):
                end += 1
            while end > i + 1 and not lines[end - 1].strip():
                end -= 1  # insert before trailing blank lines, not after
            lines.insert(
                end, f"{' ' * entry_indent}{name} ({type_text}): Seeded for the measurement."
            )
            return "\n".join(lines)
    return None


def docstring_add_deprecated(value: str, indent: str) -> str:
    """Append a ``.. deprecated::`` directive."""
    return (
        value.rstrip()
        + f"\n\n{indent}.. deprecated:: 9.9\n{indent}   Seeded for the measurement.\n{indent}"
    )


def docstring_edit_summary(value: str) -> str | None:
    """Reword the first line without touching any structured entry."""
    first, sep, rest = value.partition("\n")
    return None if not first.strip() else first.rstrip() + " (reworded)" + sep + rest
