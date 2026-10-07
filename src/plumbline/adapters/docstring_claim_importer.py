"""Docstring claim importer (PRD ING-2, ADR-0006).

A docstring knows which symbol it documents, so its claims resolve with no symbol
resolver. The importer reads Google, NumPy, and Sphinx field-list styles and states
only what a docstring says in a structured place:

    param.<p>.exists / .type / .default     returns.type
    raises.<Exc>                            deprecated

It is a pure function of the files it is given and **abstains** rather than guess:
a type that does not parse as a type, a default that is not a plain literal, a
parameter listed twice, a lone lowercase word where a return type might be. It
never states a *negative* (a docstring that does not mention ``timeout`` says
nothing about ``timeout``), because absence in prose is not a claim.

It covers the same symbols the code importer does, using the same visibility,
duplicate-definition and rebinding rules, so a claim lands on the ``Fact`` key of
the code fact it describes.
"""

from __future__ import annotations

import ast
import inspect
import keyword
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field

from plumbline.adapters import _pysource as src
from plumbline.application.ports import CommitRef, DocExtraction, RawClaim
from plumbline.domain import canonical
from plumbline.domain.anchors import Anchor

PRINCIPAL = "plumb-docstring"
_VERSION = "docstring-claim-importer/1"
_STRUCTURED = 0.95
"""A value in a structured section entry: the extractor is sure the docstring says it."""
_PROSE = 0.7
"""A default read out of free-text prose ("Defaults to 30"): plausible, less certain."""

_BUILTIN_TYPES = frozenset(
    {
        "int", "str", "float", "bool", "bytes", "bytearray", "complex", "object", "type",
        "list", "dict", "set", "frozenset", "tuple", "range", "None",
    }
)  # fmt: skip
_SECTION_LABELS = frozenset(
    {
        "note", "notes", "example", "examples", "warning", "warnings", "see", "todo", "hint",
        "tip", "important", "caution", "attention", "usage", "yields", "returns", "return",
    }
)  # fmt: skip
"""Words that open a prose paragraph (``Note: ...``), not a type, even though they parse."""

_GOOGLE_HEADER = re.compile(
    r"^(?P<h>args|arguments|parameters|params|returns?|raises?)\s*:\s*$", re.IGNORECASE
)
_GOOGLE_PARAM = re.compile(
    r"^(?P<name>\*{0,2}[A-Za-z_]\w*)\s*(?:\((?P<type>.*)\))?\s*:\s*(?P<desc>.*)$"
)
_GOOGLE_RETURNS = re.compile(r"^(?P<type>[^:]+?)\s*:\s*(?P<desc>.*)$")
_GOOGLE_RAISES = re.compile(r"^(?P<exc>[A-Za-z_][\w.]*)\s*:")
_NUMPY_UNDERLINE = re.compile(r"^(?:-{3,}|={3,}|~{3,}|\^{3,}|#{3,})\s*$")
_NUMPY_ENTRY = re.compile(r"^(?P<names>[^:]+?)\s*(?::\s*(?P<type>.*))?$")
_SPHINX_FIELD = re.compile(
    r"^:(?P<field>param|parameter|arg|argument|type|returns?|rtype|raises?|raise|except)\b"
    r"(?P<rest>[^:]*):\s*(?P<text>.*)$"
)
_DIRECTIVE = re.compile(r"^\.\.\s+deprecated::")
_KEYWORD_NOTE = re.compile(
    r"^(?:this|the)\s+(?:[*`]{0,2}\w+[*`]{0,2}\s+)?(?:keyword|parameter|argument|option)\b",
    re.IGNORECASE,
)
_USAGE_NOTE = re.compile(
    r"^(?:using|passing|calling|setting|configuring|specifying|providing|supplying)\b",
    re.IGNORECASE,
)
_OPTIONAL_PART = re.compile(r"^optional\s*(?:\(.*\))?$", re.IGNORECASE)
_QUALIFIER_PART = re.compile(
    r"^(?:keyword[- ]only|positional(?:[- ]only)?|required)$", re.IGNORECASE
)
_DEFAULT = re.compile(
    # A `default` touching a quotation mark is a value ("default", "left"), not the keyword.
    r"(?<![\"'`])\bdefaults?\b(?![\"'`])\s*(?:to|is|=|:)?\s*"
    r"(?P<v>`[^`]+`|'[^']*'|\"[^\"]*\"|[^\s,;)]+)",
    re.IGNORECASE,
)
_NAME = re.compile(r"^[A-Za-z_]\w*$")


@dataclass(slots=True)
class _Param:
    """One parameter as a docstring describes it, before canonicalization."""

    name: str
    type_text: str | None = None
    default_text: str | None = None
    default_confidence: float = _PROSE
    rule: str = ""
    optional: bool = False
    """The entry says ``optional``: the argument may be omitted, and ``None`` is allowed."""


@dataclass(slots=True)
class _DocFacts:
    """Everything one docstring states, before it is turned into claims."""

    params: list[_Param] = field(default_factory=list)
    returns: list[tuple[str, str]] = field(default_factory=list)  # (type text, rule)
    raises: list[tuple[str, str]] = field(default_factory=list)  # (exception, rule)
    deprecated: bool = False


def _indent(line: str) -> int:
    """Number of leading whitespace characters."""
    return len(line) - len(line.lstrip())


def _split_top(text: str) -> list[str]:
    """Split on commas that are not inside brackets: ``dict[str, int], optional``."""
    parts, depth, current = [], 0, ""
    for char in text:
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    parts.append(current.strip())
    return [p for p in parts if p]


def _plausible_type(text: str) -> str | None:
    """A canonical type, but only if the text *looks like* a type and not a word.

    A lone lowercase identifier (``value``, ``result``) parses as a type yet is far
    more often a name or a label, so it is rejected unless it is a builtin.
    """
    canonical_type = src.annotation_from_text(text)
    if canonical_type is None or " " in text.strip().replace(", ", ",").replace(" | ", "|"):
        return None
    bare = text.strip().strip("`")
    if bare.lower() in _SECTION_LABELS:
        return None
    if _NAME.match(bare) and bare not in _BUILTIN_TYPES and not bare[:1].isupper():
        return None
    return canonical_type


def _entries(body: list[str]) -> list[tuple[str, str]]:
    """Group a section body into ``(entry line, joined continuation text)`` pairs."""
    lines = [line for line in body if line.strip()]
    if not lines:
        return []
    base = min(_indent(line) for line in lines)
    entries: list[tuple[str, list[str]]] = []
    for line in lines:
        if _indent(line) == base:
            entries.append((line.strip(), []))
        elif entries:
            entries[-1][1].append(line.strip())
    return [(head, " ".join(rest)) for head, rest in entries]


def _default_in(text: str) -> str | None:
    """The default stated in prose such as ``Defaults to 30``, or ``None``."""
    for match in _DEFAULT.finditer(text):
        value = match["v"].strip("`").rstrip(".,;)")
        if value:
            return value
    return None


def _is_literal_value(part: str) -> bool:
    """Whether a part of a type field is a literal value (``False``, ``3``, ``'x'``), not a type.

    ``None`` is a type alternative and is not a value here.
    """
    if part.strip() == "None":
        return False
    try:
        ast.literal_eval(part.strip())
    except (ValueError, SyntaxError):
        return False
    return True


def _type_and_default(type_field: str | None) -> tuple[str | None, str | None, bool]:
    """From ``int, optional`` or ``tuple, None, optional (default None)``: type, default, optional.

    The field is split at top-level commas. ``optional`` (with or without a parenthesized
    default), ``default X`` and ``keyword only`` are qualifiers. The rest are alternatives, joined
    as a union; a leading ``or`` is dropped. If an alternative is not a type the joined text does
    not parse, and no type is claimed (ADR-0007 Amendment 7 D).
    """
    if not type_field:
        return None, None, False
    default = None
    optional = False
    alternatives: list[str] = []
    for part in _split_top(type_field):
        if _OPTIONAL_PART.match(part):
            optional = True
            default = default or _default_in(part)
        elif part.lower().startswith("default"):
            default = _default_in(part)
        elif _QUALIFIER_PART.match(part) or _is_literal_value(part):
            continue  # `bool, False`: the False is a value, not a second type
        else:
            alternatives.append(re.sub(r"^or\s+", "", part, flags=re.IGNORECASE))
    return (" | ".join(alternatives) if alternatives else None), default, optional


def _google(lines: list[str], facts: _DocFacts) -> None:
    """Collect Google-style ``Args``/``Returns``/``Raises`` sections into ``facts``."""
    i = 0
    while i < len(lines):
        header = _GOOGLE_HEADER.match(lines[i].strip()) if _indent(lines[i]) == 0 else None
        if header is None:
            i += 1
            continue
        kind = header["h"].lower()
        body: list[str] = []
        i += 1
        while i < len(lines) and (not lines[i].strip() or _indent(lines[i]) > 0):
            body.append(lines[i])
            i += 1
        _google_section(kind, body, facts)


def _google_section(kind: str, body: list[str], facts: _DocFacts) -> None:
    """Interpret one Google-style section body into ``facts``."""
    entries = _entries(body)
    if kind in ("args", "arguments", "parameters", "params"):
        for head, rest in entries:
            match = _GOOGLE_PARAM.match(head)
            if match is None or match["name"].startswith("*"):
                continue
            type_text, typed_default, optional = _type_and_default(match["type"])
            prose = _default_in(f"{match['desc']} {rest}")
            facts.params.append(
                _Param(
                    match["name"],
                    type_text,
                    typed_default or prose,
                    _STRUCTURED if typed_default else _PROSE,
                    f"docstring.google:Args '{match['name']}'",
                    optional,
                )
            )
    elif kind.startswith("return") and entries:
        match = _GOOGLE_RETURNS.match(entries[0][0])
        if match is not None:
            facts.returns.append((match["type"], "docstring.google:Returns"))
    elif kind.startswith("raise"):
        for head, _rest in entries:
            match = _GOOGLE_RAISES.match(head)
            if match is not None:
                facts.raises.append((match["exc"], "docstring.google:Raises"))


def _numpy(lines: list[str], facts: _DocFacts) -> None:
    """Collect NumPy-style underlined sections into ``facts``."""
    starts = [
        (i, lines[i].strip().lower())
        for i in range(len(lines) - 1)
        if lines[i].strip() and _NUMPY_UNDERLINE.match(lines[i + 1].strip())
    ]
    for n, (i, title) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        body = lines[i + 2 : end]
        if title in ("parameters", "other parameters"):
            _numpy_params(body, facts)
        elif title == "returns":
            entries = _entries(body)
            if len(entries) == 1:  # several return values: abstain
                head = entries[0][0]
                # `mean, median, stddev : float` names three values: no single return type.
                if ":" in head and len(_split_top(head.split(":", 1)[0])) > 1:
                    continue
                type_text = head.split(":", 1)[1].strip() if ":" in head else head
                facts.returns.append((type_text, "docstring.numpy:Returns"))
        elif title == "raises":
            for head, _rest in _entries(body):
                if re.match(r"^[A-Za-z_][\w.]*$", head):
                    facts.raises.append((head, "docstring.numpy:Raises"))


def _numpy_params(body: list[str], facts: _DocFacts) -> None:
    """Interpret a NumPy ``Parameters`` body into ``facts``."""
    for head, rest in _entries(body):
        match = _NUMPY_ENTRY.match(head)
        if match is None:
            continue
        type_text, typed_default, optional = _type_and_default(match["type"])
        prose = _default_in(rest)
        if match["type"] is None and not rest:
            continue  # a bare line of names with no type and no description is a list of types
        names = [n.strip() for n in match["names"].split(",")]
        # Every name must be a plain identifier: `{plot, diag, grid}_kws` and a wrapped line such
        # as `possible, provided the keyword ...` are not entries (Amendment 7 E). `None` alone
        # means the section has no parameters.
        if not all(_NAME.match(n) and not keyword.iskeyword(n) for n in names):
            continue
        for name in names:
            if True:
                facts.params.append(
                    _Param(
                        name,
                        type_text,
                        typed_default or prose,
                        _STRUCTURED if typed_default else _PROSE,
                        f"docstring.numpy:Parameters '{name}'",
                        optional,
                    )
                )


def _sphinx(lines: list[str], facts: _DocFacts) -> None:
    """Collect Sphinx ``:param:``/``:type:``/``:rtype:``/``:raises:`` fields into ``facts``."""
    fields: list[tuple[str, str, str]] = []
    for line in lines:
        match = _SPHINX_FIELD.match(line.strip()) if _indent(line) == 0 else None
        if match is not None:
            fields.append((match["field"], match["rest"].strip(), match["text"].strip()))
        elif fields and line.strip() and _indent(line) > 0:
            kind, rest, text = fields[-1]
            fields[-1] = (kind, rest, f"{text} {line.strip()}")
    types: dict[str, str] = {}
    for kind, rest, text in fields:
        if kind == "type" and _NAME.match(rest):
            types[rest] = text
    for kind, rest, text in fields:
        if kind in ("param", "parameter", "arg", "argument"):
            tokens = rest.rsplit(None, 1)
            name = tokens[-1] if tokens else ""
            if not _NAME.match(name):
                continue
            inline_type = tokens[0] if len(tokens) == 2 else None
            type_text, _typed_default, optional = _type_and_default(inline_type or types.get(name))
            facts.params.append(
                _Param(
                    name,
                    type_text,
                    _default_in(text),
                    _PROSE,
                    f"docstring.sphinx:param '{name}'",
                    optional,
                )
            )
        elif kind == "rtype":
            facts.returns.append((text, "docstring.sphinx:rtype"))
        elif kind in ("raises", "raise", "except") and re.match(r"^[A-Za-z_][\w.]*$", rest):
            facts.raises.append((rest, "docstring.sphinx:raises"))


def _deprecates_the_symbol(docstring: str) -> bool:
    """Whether a ``.. deprecated::`` directive is about the symbol (ADR-0007 Amendments 5 and 6).

    It must be at the docstring's top level: indented inside a parameter or any other block it
    deprecates that keyword. Its note is the first non-empty line after it, indented or not (a
    blank line often comes first); if that begins "This/The [name] keyword/parameter/argument/
    option", or a way of calling ("Using ...", "Passing ..."), the directive is not about the
    symbol itself. Ignoring a directive can only remove a claim.
    """
    lines = docstring.splitlines()
    for i, line in enumerate(lines):
        if not _DIRECTIVE.match(line):
            continue
        note = next((ln.strip() for ln in lines[i + 1 :] if ln.strip()), "")
        if not _KEYWORD_NOTE.match(note) and not _USAGE_NOTE.match(note):
            return True
    return False


def _parse(docstring: str) -> _DocFacts:
    """Parse a docstring in any supported style into the facts it states."""
    facts = _DocFacts()
    lines = inspect.cleandoc(docstring).splitlines()
    _google(lines, facts)
    _numpy(lines, facts)
    _sphinx(lines, facts)
    facts.deprecated = _deprecates_the_symbol(docstring)
    return facts


class DocstringClaimImporter:
    """Implements the `DocImporter` port for Python docstrings.

    Args:
        owner: Repository owner, for anchor URIs.
        repo: Repository name, for anchor URIs.
        include_private: Also read docstrings of underscore-prefixed symbols. Off by
            default, matching the code importer.
    """

    principal = PRINCIPAL

    def __init__(self, owner: str, repo: str, *, include_private: bool = False) -> None:
        self._owner = owner
        self._repo = repo
        self._include_private = include_private

    def handles(self, path: str) -> bool:
        """Python source files own docstring claims."""
        return path.endswith(".py")

    def extract(self, files: dict[str, bytes], commit: CommitRef) -> DocExtraction:
        """Return the docstring claims in ``files``, and which files were analyzed.

        A file that does not parse is *not* analyzed, so the apply protocol will not
        treat its silence as the docstrings having been removed.
        """
        claims: list[RawClaim] = []
        analyzed: set[str] = set()
        for path in sorted(files):
            module = src.module_name(path)
            if module is None:
                continue
            try:
                tree = ast.parse(files[path])
            except (SyntaxError, ValueError, RecursionError, MemoryError):
                continue
            analyzed.add(path)
            claims.extend(self._file_claims(path, module, tree, commit))
        return DocExtraction(
            sorted(claims, key=lambda c: (c.symbol_key, c.aspect, c.raw_value)), frozenset(analyzed)
        )

    def _documented(self, module: str, tree: ast.Module) -> Iterator[src.Definition]:
        """Definitions the code importer would also emit facts for."""
        walker = src.Walker(module)
        walker.walk(tree.body, f"{module}.", in_class=False)
        counts = Counter(d.qualname for d in walker.found)
        classes = {
            d.qualname: d.node
            for d in walker.found
            if isinstance(d.node, ast.ClassDef) and counts[d.qualname] == 1
        }
        module_bound = src.bound_names(tree.body)
        for d in walker.found:
            if counts[d.qualname] != 1:
                continue
            if not self._include_private and any(
                src.is_private(part) for part in d.qualname.split(".")[1:]
            ):
                continue
            parent, _, name = d.qualname.rpartition(".")
            if parent == module:
                if name in module_bound:
                    continue
            elif parent in classes:
                if name in src.bound_names(classes[parent].body):
                    continue
            else:
                continue  # member of an ambiguous or hidden class
            yield d

    def _file_claims(
        self, path: str, module: str, tree: ast.Module, commit: CommitRef
    ) -> list[RawClaim]:
        """Every claim made by the docstrings of one parsed file."""
        claims: list[RawClaim] = []
        for definition in self._documented(module, tree):
            docstring = ast.get_docstring(definition.node)
            if not docstring:
                continue
            facts = _parse(docstring)
            symbol = f"py:{definition.qualname}"
            anchor = Anchor(
                "repo", self._owner, self._repo, commit.sha, path, symbol=definition.qualname
            ).to_uri()
            collected: dict[str, list[tuple[str, float, str]]] = {}

            def add(aspect: str, value: str, confidence: float, rule: str) -> None:
                """Collect a candidate claim (conflicting ones are dropped later)."""
                collected.setdefault(aspect, []).append((value, confidence, rule))  # noqa: B023

            if facts.deprecated:
                add("deprecated", "true", _STRUCTURED, "docstring:.. deprecated::")
            if not isinstance(definition.node, ast.ClassDef):
                self._callable_facts(definition, facts, add)
            for aspect, found in sorted(collected.items()):
                if len({value for value, _, _ in found}) != 1:
                    continue  # the docstring says two things about one fact: abstain
                value, confidence, rule = found[0]
                claims.append(
                    RawClaim(symbol, aspect, value, anchor, confidence, f"{rule} [{_VERSION}]")
                )
        return claims

    @staticmethod
    def _callable_facts(definition: src.Definition, facts: _DocFacts, add) -> None:  # type: ignore[no-untyped-def]
        """Turn a function's parsed docstring into claims (parameters, returns, raises)."""
        receivers = {"self", "cls"} if definition.in_class else set()
        node = definition.node
        if definition.in_class and isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            # The first parameter of a method is the receiver however it is named (`def f(l1, l2)`
            # in a class), and the code importer does not list it: documenting it by its real
            # name is not documenting a parameter that does not exist.
            decorators = {
                (src.dotted(d.func if isinstance(d, ast.Call) else d) or "").rsplit(".", 1)[-1]
                for d in node.decorator_list
            }
            positional = [*node.args.posonlyargs, *node.args.args]
            if positional and "staticmethod" not in decorators:
                receivers.add(positional[0].arg)
        for param in facts.params:
            if param.name in receivers:
                continue
            add(f"param.{param.name}.exists", "true", _STRUCTURED, param.rule)
            if param.type_text is not None:
                type_value = src.annotation_from_text(param.type_text)
                allows_none = param.optional or (
                    param.default_text is not None
                    and canonical.canonical_literal(param.default_text) == "None"
                )
                if type_value is not None and allows_none:
                    type_value = canonical.canonical_type_annotation(f"{type_value} | None")
                if type_value is not None:
                    add(f"param.{param.name}.type", type_value, _STRUCTURED, param.rule)
            if param.default_text is not None:
                literal = canonical.canonical_literal(param.default_text)
                if literal is not None:
                    add(
                        f"param.{param.name}.default", literal, param.default_confidence, param.rule
                    )
        for type_text, rule in facts.returns:
            return_type = _plausible_type(type_text)
            if return_type is not None:
                add("returns.type", return_type, _STRUCTURED, rule)
        for exception, rule in facts.raises:
            add(f"raises.{exception}", "true", _STRUCTURED, rule)
