"""Static-analysis `CodeImporter` for Python source (PRD ING-1).

Reads source *text only* -- it never imports or executes the code it is given
-- so it is safe to point at hostile repositories (PRD §7.8). It emits the
**positive** L1 facts that a snapshot of source files establishes:

    exists, param_names, param.<p>.exists / .default / .type, returns.type,
    raises.<Exc>, deprecated

plus ``kind`` (module/class/function/method/attribute), which `Symbol.kind` needs
and is not a catalog aspect (ADR-0004), and deliberately nothing else:

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
from collections.abc import Sequence
from dataclasses import dataclass

from plumbline.adapters._pysource import (
    Definition as _Definition,
)
from plumbline.adapters._pysource import (
    FunctionNode as _FunctionNode,
)
from plumbline.adapters._pysource import (
    Walker as _Walker,
)
from plumbline.adapters._pysource import (
    annotation as _annotation,
)
from plumbline.adapters._pysource import (
    bound_names as _bound_names,
)
from plumbline.adapters._pysource import (
    dotted as _dotted,
)
from plumbline.adapters._pysource import (
    is_private as _is_private,
)
from plumbline.adapters._pysource import (
    module_name as _module_name,
)
from plumbline.adapters._pysource import (
    scope_nodes as _scope_nodes,
)
from plumbline.application.ports import CommitRef, RawClaim
from plumbline.domain import canonical
from plumbline.domain.anchors import Anchor

_EXTRACTOR_CONFIDENCE = 1.0
"""Static analysis of the syntax tree: fidelity is certain; only *truth* is in question."""


def _wrapper_decorators(tree: ast.Module) -> frozenset[str]:
    """Names of functions in this file that are decorators built with ``functools.wraps``.

    A decorator that wraps with ``@wraps(f)`` forwards the call and keeps the signature,
    which is the near-universal convention (a locking or retry wrapper). Only decorators
    defined in the *same file* can be recognised; an imported one is opaque.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for inner in ast.walk(node):
            if inner is node or not isinstance(inner, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if any(
                (_dotted(d.func if isinstance(d, ast.Call) else d) or "").rsplit(".", 1)[-1]
                == "wraps"
                for d in inner.decorator_list
            ):
                found.add(node.name)
    return frozenset(found)


def _signature_is_trustworthy(func: _FunctionNode, wrappers: frozenset[str] = frozenset()) -> bool:
    """Whether the ``def``'s own signature is the callable's effective signature."""
    for decorator in func.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = (_dotted(target) or "").rsplit(".", 1)[-1]
        if name not in _SIGNATURE_SAFE_DECORATORS and name not in wrappers:
            return False
    return True


def _message_text(call: ast.Call) -> str:
    """The text of a ``warn`` call's message, lower-cased (string, f-string, or concatenation)."""
    if not call.args:
        return ""
    return "".join(
        node.value.lower()
        for node in ast.walk(call.args[0])
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def _warn_category(call: ast.Call) -> str:
    """The last name of a ``warn`` call's category, positional or ``category=``, else ``""``."""
    candidates = list(call.args[1:2]) + [k.value for k in call.keywords if k.arg == "category"]
    return (_dotted(candidates[0]) or "").rsplit(".", 1)[-1] if candidates else ""


def _is_warn(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and (_dotted(node.func) or "").rsplit(".", 1)[-1] == "warn"


def _is_deprecation_helper(node: ast.AST) -> bool:
    """A call to a function whose name says it deprecates (``warn_deprecated``), ADR-0004 A4."""
    return (
        isinstance(node, ast.Call)
        and "deprecat" in (_dotted(node.func) or "").lower().rsplit(".", 1)[-1]
    )


def _says_deprecated(call: ast.Call) -> bool:
    """Whether a call's first string argument says "deprecated", whatever the callee is named.

    A project's own ``emit_user_level_warning("f() is deprecated ...")`` is a notice by its
    message and not by its name (ADR-0004 Amendment 5 B).
    """
    return "deprecat" in _message_text(call)


def _is_deprecation_warning(call: ast.Call) -> bool:
    """Whether ``call`` is a notice that the code is deprecated (ADR-0004 Amendments 3 to 5).

    A ``warn`` with category ``DeprecationWarning`` or ``PendingDeprecationWarning``, a call to
    a function whose name says it deprecates, or any call whose message says so.
    """
    return (
        _is_deprecation_helper(call)
        or _says_deprecated(call)
        or (
            _is_warn(call)
            and _warn_category(call) in ("DeprecationWarning", "PendingDeprecationWarning")
        )
    )


def _mentions_deprecation(call: ast.Call) -> bool:
    """Whether a call might be a deprecation notice, however it is phrased."""
    return _is_deprecation_warning(call)


def _decorator_names(node: _FunctionNode | ast.ClassDef) -> list[str]:
    return [
        (_dotted(d.func if isinstance(d, ast.Call) else d) or "").rsplit(".", 1)[-1]
        for d in node.decorator_list
    ]


def _leading_statement(func: _FunctionNode) -> ast.stmt | None:
    """The first statement that is not the docstring or an import."""
    for stmt in func.body:
        if isinstance(stmt, ast.Import | ast.ImportFrom):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue  # the docstring
        return stmt
    return None


def _init_of(cls: ast.ClassDef) -> _FunctionNode | None:
    """The class's own ``__init__``, if it defines one."""
    return next(
        (
            stmt
            for stmt in cls.body
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef) and stmt.name == "__init__"
        ),
        None,
    )


def _has_leading_notice(func: _FunctionNode) -> bool:
    """Whether the first statement (after docstring and imports) is a deprecation notice."""
    leading = _leading_statement(func)
    return (
        isinstance(leading, ast.Expr)
        and isinstance(leading.value, ast.Call)
        and _is_deprecation_warning(leading.value)
    )


def _deprecation(node: _FunctionNode | ast.ClassDef) -> bool | None:
    """``True`` if a deprecation marker is visible, ``False`` if provably none, else ``None``.

    A docstring only ever claims deprecation, so a wrong ``True`` cannot open a dispute and a
    wrong ``False`` can: the answer is ``False`` only when nothing could be hiding one (an
    unknown decorator, or a deprecation notice somewhere other than the start of the body). A
    class is judged by its decorators and by its own ``__init__`` (ADR-0004 Amendment 5 A).
    """
    names = _decorator_names(node)
    if "deprecated" in names:
        return True
    body = _init_of(node) if isinstance(node, ast.ClassDef) else node
    if body is not None and _has_leading_notice(body):
        return True
    if any(name not in _DEPRECATION_NEUTRAL_DECORATORS for name in names):
        return None
    if body is not None and any(
        _mentions_deprecation(call) for call in ast.walk(body) if isinstance(call, ast.Call)
    ):
        return None
    return False


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


_ALLOWED_CLASS_DECORATORS = frozenset(
    {"final", "runtime_checkable", "deprecated", "type_check_only"}
)
_DEPRECATION_NEUTRAL_DECORATORS = frozenset(
    {
        "staticmethod", "classmethod", "abstractmethod", "property", "getter", "setter",
        "deleter", "final", "override", "cache", "lru_cache", "cached_property", "overload",
        "dataclass", "total_ordering", "runtime_checkable", "type_check_only",
    }
)  # fmt: skip
"""Decorators that cannot deprecate what they decorate, so their presence does not make
"not deprecated" a claim we cannot back (ADR-0004 Amendment 3)."""
_PROPERTY_DECORATORS = frozenset({"property", "cached_property", "getter", "setter", "deleter"})
"""A property is accessed, not called: its docstring describes the object it returns."""
_SIGNATURE_SAFE_DECORATORS = frozenset(
    {
        "staticmethod", "classmethod", "abstractmethod", "property", "getter", "setter",
        "deleter", "final", "override", "deprecated", "cache", "lru_cache", "cached_property",
    }
)  # fmt: skip
"""Decorators known to leave a callable's call signature as written (ADR-0007 §5).

Any other decorator may rewrite it (a CLI command decorator, a wrapper that adds
parameters), so for those the importer states nothing about the signature rather than
risk a projection that is false at runtime."""

_NAMESPACE_CALLS = frozenset({"globals", "vars", "locals", "exec", "eval"})
_OPEN_CLASS_METHODS = frozenset({"__getattr__", "__getattribute__"})
_RECEIVER_MUTATORS = frozenset({"setattr", "delattr", "vars"})


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
        emit.fact(f"py:{module}", "kind", "module", 1, end, "ast.Module")
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

        wrappers = _wrapper_decorators(tree)
        counts = Counter(d.qualname for d in walker.found)
        unique = [d for d in walker.found if counts[d.qualname] == 1 and self._visible(d.qualname)]
        ambiguous = {
            d.qualname: d
            for d in reversed(walker.found)  # reversed, so the first definition's span wins
            if counts[d.qualname] > 1 and self._visible(d.qualname)
        }
        for qualname, first in sorted(ambiguous.items()):
            # The name certainly exists, but which definition it is -- and so every
            # detail fact -- is not knowable. Say so, so absence is never inferred (ADR-0005).
            key = f"py:{qualname}"
            node = first.node
            emit.fact(key, "exists", "true", node.lineno, _end(node), "defined more than once")
            emit.fact(key, "kind", "ambiguous", node.lineno, _end(node), "defined more than once")
        scopes = {
            d.qualname: _class_scope(d.node) for d in unique if isinstance(d.node, ast.ClassDef)
        }
        defined = {d.qualname for d in unique} | ambiguous.keys()

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
                emit,
                definition,
                rebound=rebound,
                scope=scopes.get(definition.qualname),
                wrappers=wrappers,
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
            emit.fact(f"py:{qualname}", "kind", "attribute", line, line, "name bound in namespace")

    def _definition_claims(
        self,
        emit: _Emitter,
        definition: _Definition,
        *,
        rebound: bool,
        scope: _ClassScope | None,
        wrappers: frozenset[str] = frozenset(),
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
            # The name is also assigned, so it may no longer be this definition.
            emit.fact(key, "kind", "attribute", start, end, "name also bound by assignment")
            return
        emit.fact(key, "kind", _kind_of(node, definition.in_class), start, end, "definition kind")
        deprecation = _deprecation(node)
        if deprecation is not None:
            emit.fact(
                key,
                "deprecated",
                canonical.canonical_bool(deprecation),
                start,
                end,
                "deprecation marker (decorator, or a warning that says so, at entry)",
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
        if not _signature_is_trustworthy(node, wrappers):
            return  # a decorator may have rewritten the signature: say nothing about it
        for exc in _raised_exceptions(node):
            emit.fact(key, f"raises.{exc}", "true", start, end, "direct `raise` in body")
        if _PROPERTY_DECORATORS.intersection(_decorator_names(node)):
            return  # its docstring describes the returned object's call, not this signature
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


def _kind_of(node: _FunctionNode | ast.ClassDef, in_class: bool) -> str:
    """The `Symbol.kind` of a definition."""
    if isinstance(node, ast.ClassDef):
        return "class"
    return "method" if in_class else "function"


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
