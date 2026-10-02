"""Static-analysis `CodeImporter` for Python source (PRD ING-1).

Reads source *text only* -- it never imports or executes the code it is given
-- so it is safe to point at hostile repositories (PRD §7.8). It emits the
**positive** L1 facts that a snapshot of source files establishes:

    exists, param_names, param.<p>.exists / .default / .type, returns.type,
    raises.<Exc>, deprecated

and deliberately nothing else:

* **Absence is not its job.** "This symbol no longer exists" is a fact about
  the *difference* between a snapshot and the KB's current state (PRD §7.7:
  importers diff against the KB), so it is derived downstream, not here.
* **It abstains whenever it cannot be sure** (PRD §3 principle 3, DRF-3): a
  default that is not a plain literal, a symbol defined more than once in a
  module (e.g. in both branches of an ``if``), a file that does not parse.
  Abstaining means emitting *no claim* for that slot.
* **Closure (ADR-0003).** For modules and classes it also emits
  ``namespace_closed``: ``true`` only when the member names are fully
  determined by the source, so the projector may later treat a missing name as
  *absent* rather than *unknown*. That promise is only sound if every name the
  namespace binds has been listed, so it also emits ``exists`` for names bound
  by assignment, import, and ``self.<attr> = ...``, not just ``def``/``class``.
* ``added_in`` / ``removed_in`` come from the lineage reasoner, and the
  ``cli.*``, ``env.*`` and ``project.*`` aspects are separate importers.

Values are emitted already canonical (via `plumbline.domain.canonical`),
because only this layer still holds the syntax tree needed to canonicalize them.
"""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field

from plumbline.application.ports import CommitRef, RawClaim
from plumbline.domain import canonical
from plumbline.domain.anchors import Anchor

_EXTRACTOR_CONFIDENCE = 1.0
"""Static analysis of the syntax tree: fidelity is certain; only *truth* is in question."""

_FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
_TYPING_MODULES = ("typing.", "typing_extensions.")


def _is_private(name: str) -> bool:
    """Single/double-underscore names are private; dunders like ``__init__`` are not."""
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _module_name(path: str) -> str | None:
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


def _dotted(node: ast.expr) -> str | None:
    """``a.b.c`` for a pure Name/Attribute chain, else ``None``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return None if base is None else f"{base}.{node.attr}"
    return None


class _NormalizeAnnotation(ast.NodeTransformer):
    """Rewrite ``Optional[X]`` / ``Union[A, B]`` to PEP 604 form and drop ``typing.``."""

    def visit_Subscript(self, node: ast.Subscript) -> ast.expr:
        """Rewrite ``Optional[X]`` and ``Union[...]`` subscripts to PEP 604 unions."""
        self.generic_visit(node)
        name = _dotted(node.value) or ""
        short = name.rsplit(".", 1)[-1]
        if short == "Optional":
            return ast.BinOp(left=node.slice, op=ast.BitOr(), right=ast.Constant(value=None))
        if short == "Union" and isinstance(node.slice, ast.Tuple) and node.slice.elts:
            result = node.slice.elts[0]
            for member in node.slice.elts[1:]:
                result = ast.BinOp(left=result, op=ast.BitOr(), right=member)
            return result
        return node


def _annotation(node: ast.expr) -> str:
    """Canonical text of an annotation expression."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return canonical.canonical_type_annotation(node.value)  # quoted forward reference
    tree = _NormalizeAnnotation().visit(ast.fix_missing_locations(node))
    text = ast.unparse(tree)
    for prefix in _TYPING_MODULES:
        text = text.replace(prefix, "")
    return canonical.canonical_type_annotation(text)


def _is_deprecation_warning(call: ast.Call) -> bool:
    """Whether ``call`` is ``warn(..., DeprecationWarning)`` (positional or ``category=``)."""
    func = _dotted(call.func) or ""
    if func.rsplit(".", 1)[-1] != "warn":
        return False
    candidates = list(call.args[1:2]) + [k.value for k in call.keywords if k.arg == "category"]
    return any((_dotted(c) or "").rsplit(".", 1)[-1] == "DeprecationWarning" for c in candidates)


def _is_deprecated(func: _FunctionNode | ast.ClassDef) -> bool:
    """A ``@deprecated`` decorator, or (functions) a DeprecationWarning at entry."""
    for decorator in func.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if (_dotted(target) or "").rsplit(".", 1)[-1] == "deprecated":
            return True
    if isinstance(func, ast.ClassDef):
        return False
    body = func.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]  # skip the docstring
    first = body[0] if body else None
    return (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Call)
        and _is_deprecation_warning(first.value)
    )


def _raised_exceptions(func: _FunctionNode) -> list[str]:
    """Exceptions raised *directly* in ``func`` (not in nested functions or classes)."""
    found: list[str] = []
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
            continue
        if isinstance(node, ast.Raise) and node.exc is not None:
            target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            name = _dotted(target)
            # Only names that look like a class (``raise exc`` re-raises a variable).
            if name is not None and name.rsplit(".", 1)[-1][:1].isupper():
                found.append(name)
        stack.extend(ast.iter_child_nodes(node))
    return sorted(set(found))


@dataclass(frozen=True, slots=True)
class _Definition:
    """One function, method, or class found in a module."""

    qualname: str
    node: _FunctionNode | ast.ClassDef
    in_class: bool


@dataclass(slots=True)
class _Walker:
    """Collects definitions, descending through ``if``/``try``/``with`` and class bodies."""

    module: str
    found: list[_Definition] = field(default_factory=list)

    def walk(self, body: list[ast.stmt], prefix: str, in_class: bool) -> None:
        """Collect definitions from ``body``, recursing into compound statements and classes."""
        for stmt in body:
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                if any((_dotted(d) or "").endswith("overload") for d in stmt.decorator_list):
                    continue  # typing stubs, not definitions
                self.found.append(_Definition(f"{prefix}{stmt.name}", stmt, in_class))
            elif isinstance(stmt, ast.ClassDef):
                self.found.append(_Definition(f"{prefix}{stmt.name}", stmt, in_class))
                self.walk(stmt.body, f"{prefix}{stmt.name}.", in_class=True)
            elif isinstance(stmt, ast.If | ast.With | ast.AsyncWith | ast.For | ast.While):
                self.walk(stmt.body, prefix, in_class)
                self.walk(stmt.orelse if hasattr(stmt, "orelse") else [], prefix, in_class)
            elif isinstance(stmt, ast.Try):
                for block in (stmt.body, stmt.orelse, stmt.finalbody):
                    self.walk(block, prefix, in_class)
                for handler in stmt.handlers:
                    self.walk(handler.body, prefix, in_class)


_ALLOWED_CLASS_DECORATORS = frozenset(
    {"final", "runtime_checkable", "deprecated", "type_check_only"}
)
_NAMESPACE_CALLS = frozenset({"globals", "vars", "locals", "exec", "eval"})
_OPEN_CLASS_METHODS = frozenset({"__getattr__", "__getattribute__"})
_RECEIVER_MUTATORS = frozenset({"setattr", "delattr", "vars"})


def _scope_nodes(body: Iterable[ast.AST], *, into_classes: bool = False) -> Iterator[ast.AST]:
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


def _bound_names(body: Iterable[ast.AST]) -> dict[str, int]:
    """Names bound in this namespace by something other than ``def``/``class``, with first line."""
    found: dict[str, int] = {}

    def bind(name: str, line: int) -> None:
        found[name] = min(line, found.get(name, line))

    for node in _scope_nodes(body):
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


def _is_namespace_call(node: ast.AST) -> bool:
    """``globals()``/``vars()``/``locals()``/``exec()``/``eval()``: names chosen at runtime."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _NAMESPACE_CALLS
    )


def _module_is_closed(tree: ast.Module, found: Sequence[_Definition], module: str) -> bool:
    """Whether the module's attribute names are fully determined by its source (ADR-0003)."""
    if any(d.qualname == f"{module}.__getattr__" for d in found):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):  # binds module names at runtime
            return False
        if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
            return False
    for node in _scope_nodes(tree.body, into_classes=True):
        if _is_namespace_call(node):
            return False
        if isinstance(node, ast.Subscript) and _dotted(node.value) == "sys.modules":
            return False
    return True


@dataclass(slots=True)
class _ClassScope:
    """A class's closure verdict and the member names it binds."""

    closed: bool
    names: dict[str, int]


def _class_header_is_closed(node: ast.ClassDef) -> bool:
    """Bases, keywords, and decorators that cannot add or inherit unseen members."""
    if node.keywords:
        return False
    # Any base but `object` may supply inherited members the importer was never
    # shown -- including an in-file base, until inheritance is modelled (ADR-0003).
    if any(not (isinstance(b, ast.Name) and b.id == "object") for b in node.bases):
        return False
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if (_dotted(target) or "").rsplit(".", 1)[-1] not in _ALLOWED_CLASS_DECORATORS:
            return False
    return True


def _class_scope(node: ast.ClassDef) -> _ClassScope:
    """Closure verdict for a class, plus every member name it binds (including ``self.x``)."""
    names = _bound_names(node.body)
    closed = _class_header_is_closed(node)
    for member in _scope_nodes(node.body):
        if _is_namespace_call(member):
            closed = False  # e.g. `vars()` / `locals()` filling the class body
        method = member
        if not isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if method.name in _OPEN_CLASS_METHODS:
            closed = False
        decorators = {(_dotted(d) or "").rsplit(".", 1)[-1] for d in method.decorator_list}
        params = [*method.args.posonlyargs, *method.args.args]
        if not params or "staticmethod" in decorators:
            continue
        receiver = params[0].arg
        for inner in ast.walk(method):
            if (
                isinstance(inner, ast.Attribute)
                and isinstance(inner.value, ast.Name)
                and inner.value.id == receiver
            ):
                if isinstance(inner.ctx, ast.Store):
                    names.setdefault(inner.attr, inner.lineno)
                elif inner.attr == "__dict__":
                    closed = False
            elif (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id in _RECEIVER_MUTATORS
                and inner.args
                and isinstance(inner.args[0], ast.Name)
                and inner.args[0].id == receiver
            ):
                closed = False  # setattr(self, ...) etc.: names chosen at runtime
    return _ClassScope(closed, names)


class PythonCodeImporter:
    """Implements the `CodeImporter` port for Python source files.

    Args:
        owner: Repository owner, for anchor URIs.
        repo: Repository name, for anchor URIs.
        include_private: Also emit facts for underscore-prefixed symbols. Off by
            default: PRD §13 Q6 leans toward public symbols only, because
            private ones roughly triple the KB.
    """

    def __init__(self, owner: str, repo: str, *, include_private: bool = False) -> None:
        self._owner = owner
        self._repo = repo
        self._include_private = include_private

    def extract(self, files: dict[str, bytes], commit: CommitRef) -> list[RawClaim]:
        """Return the code facts established by ``files`` at ``commit``.

        Output order is independent of the order of ``files``.
        """
        claims: list[RawClaim] = []
        for path in sorted(files):
            module = _module_name(path)
            if module is None:
                continue
            try:
                tree = ast.parse(files[path])
            except (SyntaxError, ValueError, RecursionError, MemoryError):
                continue  # unparseable or hostile: abstain for the whole file
            claims.extend(self._file_claims(path, module, tree, commit))
        return sorted(claims, key=lambda c: (c.symbol_key, c.aspect))

    def _file_claims(
        self, path: str, module: str, tree: ast.Module, commit: CommitRef
    ) -> list[RawClaim]:
        """All claims for one source file: the module, its bound names, and each definition."""
        emit = _Emitter(self._owner, self._repo, path, commit)
        end = _end(tree)
        emit.fact(f"py:{module}", "exists", "true", 1, end, "ast.Module present")
        walker = _Walker(module)
        walker.walk(tree.body, f"{module}.", in_class=False)
        emit.fact(
            f"py:{module}",
            "namespace_closed",
            canonical.canonical_bool(_module_is_closed(tree, walker.found, module)),
            1,
            end,
            "module attribute names fully determined by source (ADR-0003)",
        )

        counts = Counter(d.qualname for d in walker.found)
        unique = [d for d in walker.found if counts[d.qualname] == 1 and self._visible(d.qualname)]
        scopes = {
            d.qualname: _class_scope(d.node) for d in unique if isinstance(d.node, ast.ClassDef)
        }
        defined = {d.qualname for d in unique}

        module_bound = _bound_names(tree.body)
        self._bound_claims(emit, module, module_bound, defined)
        for qualname, scope in scopes.items():
            self._bound_claims(emit, qualname, scope.names, defined)

        for definition in unique:
            parent, _, name = definition.qualname.rpartition(".")
            if parent == module:
                rebound = name in module_bound
            elif parent in scopes:
                rebound = name in scopes[parent].names
            else:
                continue  # member of an ambiguous or hidden class: abstain
            self._definition_claims(
                emit, definition, rebound=rebound, scope=scopes.get(definition.qualname)
            )
        return emit.claims

    def _visible(self, qualname: str) -> bool:
        """Whether a symbol is emitted at all, given the privacy setting."""
        if self._include_private:
            return True
        return not any(_is_private(part) for part in qualname.split(".")[1:])

    def _bound_claims(
        self, emit: _Emitter, scope: str, names: dict[str, int], defined: set[str]
    ) -> None:
        """``exists`` for names bound by assignment, import, or ``self.x`` (not def/class)."""
        for name, line in sorted(names.items()):
            qualname = f"{scope}.{name}"
            if qualname in defined or not name.isidentifier() or not self._visible(qualname):
                continue
            emit.fact(f"py:{qualname}", "exists", "true", line, line, "name bound in namespace")

    def _definition_claims(
        self,
        emit: _Emitter,
        definition: _Definition,
        *,
        rebound: bool,
        scope: _ClassScope | None,
    ) -> None:
        """Claims for one function, method, or class.

        A name that is also assigned elsewhere in its namespace (``f = wrap(f)``)
        may no longer be this definition, so only its existence is claimed.
        """
        node = definition.node
        key = f"py:{definition.qualname}"
        start, end = node.lineno, _end(node)
        emit.fact(key, "exists", "true", start, end, f"ast.{type(node).__name__} present")
        if rebound:
            return
        emit.fact(
            key,
            "deprecated",
            canonical.canonical_bool(_is_deprecated(node)),
            start,
            end,
            "deprecation marker (decorator or DeprecationWarning at entry)",
        )
        if isinstance(node, ast.ClassDef):
            if scope is not None:
                emit.fact(
                    key,
                    "namespace_closed",
                    canonical.canonical_bool(scope.closed),
                    start,
                    end,
                    "class member names fully determined by source (ADR-0003)",
                )
            return
        for exc in _raised_exceptions(node):
            emit.fact(key, f"raises.{exc}", "true", start, end, "direct `raise` in body")
        self._signature_claims(emit, key, node, definition.in_class)

    def _signature_claims(
        self, emit: _Emitter, key: str, node: _FunctionNode, in_class: bool
    ) -> None:
        """Claims derived from a function's parameters, defaults, and annotations."""
        start, end = node.lineno, _end(node)
        args = node.args
        positional = [*args.posonlyargs, *args.args]
        defaults: dict[str, ast.expr] = {}
        for arg, default in zip(reversed(positional), reversed(args.defaults), strict=False):
            defaults[arg.arg] = default
        for arg, kw_default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
            if kw_default is not None:
                defaults[arg.arg] = kw_default

        decorators = {(_dotted(d) or "").rsplit(".", 1)[-1] for d in node.decorator_list}
        if in_class and "staticmethod" not in decorators and positional:
            positional = positional[1:]  # drop self / cls

        named = [*positional, *args.kwonlyargs]
        names = [a.arg for a in positional]
        if args.vararg is not None:
            names.append(f"*{args.vararg.arg}")
        names.extend(a.arg for a in args.kwonlyargs)
        if args.kwarg is not None:
            names.append(f"**{args.kwarg.arg}")
        emit.fact(
            key,
            "param_names",
            canonical.canonical_param_names(names),
            start,
            end,
            "signature parameter order",
        )

        for arg in named:
            line = arg.lineno
            emit.fact(key, f"param.{arg.arg}.exists", "true", line, line, "named parameter")
            if arg.arg in defaults:
                literal = canonical.canonical_literal(ast.unparse(defaults[arg.arg]))
                if literal is not None:  # non-literal default: abstain
                    emit.fact(
                        key, f"param.{arg.arg}.default", literal, line, line, "literal default"
                    )
            if arg.annotation is not None:
                emit.fact(
                    key,
                    f"param.{arg.arg}.type",
                    _annotation(arg.annotation),
                    line,
                    line,
                    "parameter annotation",
                )
        if node.returns is not None:
            emit.fact(
                key, "returns.type", _annotation(node.returns), start, end, "return annotation"
            )


def _end(node: ast.AST) -> int:
    """Last source line of ``node`` (a module spans its last statement)."""
    if isinstance(node, ast.Module):
        return max((_end(stmt) for stmt in node.body), default=1)
    end = getattr(node, "end_lineno", None)
    return end if isinstance(end, int) else 1


class _Emitter:
    """Builds `RawClaim`s for one file at one commit."""

    def __init__(self, owner: str, repo: str, path: str, commit: CommitRef) -> None:
        self._owner = owner
        self._repo = repo
        self._path = path
        self._sha = commit.sha
        self.claims: list[RawClaim] = []

    def fact(
        self, symbol_key: str, aspect: str, value: str, start: int, end: int, rationale: str
    ) -> None:
        """Append one claim, anchored to ``start``-``end`` of this file at this commit."""
        anchor = Anchor(
            scheme="repo",
            owner=self._owner,
            repo=self._repo,
            commit_sha=self._sha,
            path=self._path,
            line_start=start,
            line_end=max(start, end),
        )
        self.claims.append(
            RawClaim(
                symbol_key=symbol_key,
                aspect=aspect,
                raw_value=value,
                anchor_uri=anchor.to_uri(),
                confidence=_EXTRACTOR_CONFIDENCE,
                rationale=rationale,
            )
        )
