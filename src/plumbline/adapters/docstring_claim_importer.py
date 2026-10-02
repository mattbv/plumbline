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
_NUMPY_UNDERLINE = re.compile(r"^-{3,}\s*$")
_NUMPY_ENTRY = re.compile(r"^(?P<names>[^:]+?)\s*(?::\s*(?P<type>.*))?$")
_SPHINX_FIELD = re.compile(
    r"^:(?P<field>param|parameter|arg|argument|type|returns?|rtype|raises?|raise|except)\b"
    r"(?P<rest>[^:]*):\s*(?P<text>.*)$"
)
_DEPRECATED = re.compile(r"^\s*\.\.\s+deprecated::", re.MULTILINE)
_DEFAULT = re.compile(
    r"\bdefaults?\b\s*(?:to|is|=|:)?\s*"
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
    match = _DEFAULT.search(text)
    if match is None:
        return None
    value = match["v"].strip("`").rstrip(".,;)")
    return value or None


def _type_and_default(type_field: str | None) -> tuple[str | None, str | None]:
    """From ``int, optional`` or ``int, default 30``: the type, and a default if stated."""
    if not type_field:
        return None, None
    parts = _split_top(type_field)
    default = None
    for extra in parts[1:]:
        if extra.lower().startswith("default"):
            default = _default_in(extra)
    return (parts[0] if parts else None), default


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
            type_text, typed_default = _type_and_default(match["type"])
            prose = _default_in(f"{match['desc']} {rest}")
            facts.params.append(
                _Param(
                    match["name"],
                    type_text,
                    typed_default or prose,
                    _STRUCTURED if typed_default else _PROSE,
                    f"docstring.google:Args '{match['name']}'",
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
        type_text, typed_default = _type_and_default(match["type"])
        prose = _default_in(rest)
        for name in (n.strip() for n in match["names"].split(",")):
            if _NAME.match(name):
                facts.params.append(
                    _Param(
                        name,
                        type_text,
                        typed_default or prose,
                        _STRUCTURED if typed_default else _PROSE,
                        f"docstring.numpy:Parameters '{name}'",
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
            facts.params.append(
                _Param(
                    name,
                    inline_type or types.get(name),
                    _default_in(text),
                    _PROSE,
                    f"docstring.sphinx:param '{name}'",
                )
            )
        elif kind == "rtype":
            facts.returns.append((text, "docstring.sphinx:rtype"))
        elif kind in ("raises", "raise", "except") and re.match(r"^[A-Za-z_][\w.]*$", rest):
            facts.raises.append((rest, "docstring.sphinx:raises"))


def _parse(docstring: str) -> _DocFacts:
    """Parse a docstring in any supported style into the facts it states."""
    facts = _DocFacts()
    lines = inspect.cleandoc(docstring).splitlines()
    _google(lines, facts)
    _numpy(lines, facts)
    _sphinx(lines, facts)
    facts.deprecated = bool(_DEPRECATED.search(docstring))
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
        for param in facts.params:
            if param.name in receivers:
                continue
            add(f"param.{param.name}.exists", "true", _STRUCTURED, param.rule)
            if param.type_text is not None:
                type_value = src.annotation_from_text(param.type_text)
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
