"""Assemble a commit's importer claims into L1 ``Symbol`` fields (ADR-0004).

The code importer emits atomic per-aspect facts; L1 stores a handful of coarse
``time_varying`` ``Symbol`` fields. This module is the pure bridge between them:

    exists            -> present            (always "true"; "false" is derived by
                                             the snapshot-vs-KB diff, never extracted)
    deprecated        -> is_deprecated
    namespace_closed  -> namespace_closed   (modules and classes)
    kind              -> kind
    exists' anchor    -> defined_at         (the definition's *path*; the SHA and
                                             lines live in each assertion's provenance)
    everything else   -> signature_json     (canonical blob, `plumbline.domain.signature`)

`aspects_of` is the inverse, i.e. the read side the drift projector will use.
Both are deterministic and perform no I/O.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from plumbline.application.ports import RawClaim
from plumbline.domain import anchors, signature

KINDS = frozenset({"module", "class", "function", "method", "attribute", "ambiguous"})

_RANK = {"module": 3, "class": 2, "function": 2, "method": 2, "ambiguous": 2, "attribute": 1}
_SIGNATURE_KINDS = frozenset({"function", "method"})
_DIRECT = {"exists", "deprecated", "namespace_closed", "kind"}


def kind_rank(kind: str) -> int:
    """Precedence when two paths claim one key: module > definition > attribute (ADR-0005)."""
    return _RANK[kind]


@dataclass(frozen=True, slots=True)
class KeyConflict:
    """Two paths claimed one symbol key; ``dropped_path`` lost to ``kept_path``."""

    symbol_key: str
    kept_path: str
    dropped_path: str


@dataclass(frozen=True, slots=True)
class SymbolFields:
    """The L1 ``Symbol`` assertions for one symbol after one commit.

    ``None`` means "write nothing for this field" (the importer made no claim).
    ``anchor`` is the SHA-pinned anchor of the definition; it is not a field but
    the ``source`` (provenance) of every assertion written for this symbol.
    """

    kind: str
    present: str
    defined_at: str
    anchor: str
    is_deprecated: str | None = None
    namespace_closed: str | None = None
    signature_json: str | None = None

    def as_mapping(self) -> dict[str, str]:
        """The fields to write, keyed by ``Symbol`` field name."""
        pairs = {
            "kind": self.kind,
            "present": self.present,
            "defined_at": self.defined_at,
            "is_deprecated": self.is_deprecated,
            "namespace_closed": self.namespace_closed,
            "signature_json": self.signature_json,
        }
        return {name: value for name, value in pairs.items() if value is not None}


def _path(claim: RawClaim) -> str:
    """The path a claim's anchor points at."""
    return anchors.parse(claim.anchor_uri).path


def _by_key_and_path(claims: Iterable[RawClaim]) -> dict[str, dict[str, list[RawClaim]]]:
    """Group claims by symbol key, then by the path that made them."""
    grouped: dict[str, dict[str, list[RawClaim]]] = defaultdict(lambda: defaultdict(list))
    for claim in claims:
        grouped[claim.symbol_key][_path(claim)].append(claim)
    return grouped


def emitting_paths(claims: Iterable[RawClaim]) -> dict[str, frozenset[str]]:
    """Which paths emitted claims for each symbol key (usually one; two means a collision)."""
    return {key: frozenset(paths) for key, paths in _by_key_and_path(claims).items()}


def assemble(claims: Iterable[RawClaim]) -> dict[str, SymbolFields]:
    """Group claims by symbol and assemble each symbol's L1 fields.

    If two paths claim the same key (a package's ``from . import sub`` binds an
    attribute with the key of the ``sub`` module), the higher-ranked kind wins and
    a tie goes to the lexicographically first path, so the result is deterministic
    (ADR-0005). `find_conflicts` reports what lost.

    Args:
        claims: Everything the code importer emitted for a commit.

    Returns:
        ``{symbol_key: SymbolFields}``, ordered by symbol key.

    Raises:
        ValueError: A symbol lacks ``exists`` or ``kind``, repeats an aspect within
            one path, has an unknown ``kind``, or carries signature facts but is
            not a function or method. The importer never produces these, so they
            signal a bug rather than hostile input.
    """
    grouped = _by_key_and_path(claims)
    return {key: _winner(key, grouped[key])[0] for key in sorted(grouped)}


def find_conflicts(claims: Iterable[RawClaim]) -> list[KeyConflict]:
    """Every key claimed from more than one path, with who kept it and who lost."""
    conflicts: list[KeyConflict] = []
    for key, by_path in sorted(_by_key_and_path(claims).items()):
        if len(by_path) > 1:
            kept = _winner(key, by_path)[1]
            conflicts.extend(
                KeyConflict(key, kept, path) for path in sorted(by_path) if path != kept
            )
    return conflicts


def _winner(key: str, by_path: dict[str, list[RawClaim]]) -> tuple[SymbolFields, str]:
    """The owning path's fields for a key claimed from one or more paths."""
    candidates = {path: _assemble_one(key, claims) for path, claims in by_path.items()}
    path = min(candidates, key=lambda p: (-kind_rank(candidates[p].kind), p))
    return candidates[path], path


def _assemble_one(symbol_key: str, claims: list[RawClaim]) -> SymbolFields:
    """Assemble one symbol's fields from the claims of a single path."""
    by_aspect = {c.aspect: c for c in claims}
    if len(by_aspect) != len(claims):
        raise ValueError(f"{symbol_key}: an aspect is claimed more than once")
    exists, kind = by_aspect.get("exists"), by_aspect.get("kind")
    if exists is None or kind is None:
        raise ValueError(f"{symbol_key}: needs both 'exists' and 'kind' claims")
    if kind.raw_value not in KINDS:
        raise ValueError(f"{symbol_key}: unknown kind {kind.raw_value!r}")
    if exists.raw_value != "true":
        raise ValueError(f"{symbol_key}: the importer only ever claims existence as 'true'")

    signature_pairs = [(c.aspect, c.raw_value) for c in claims if c.aspect not in _DIRECT]
    blob: str | None = None
    if signature_pairs:
        if kind.raw_value not in _SIGNATURE_KINDS:
            raise ValueError(f"{symbol_key}: a {kind.raw_value} cannot have signature facts")
        blob = signature.to_json(signature.from_claims(signature_pairs))

    deprecated = by_aspect.get("deprecated")
    closed = by_aspect.get("namespace_closed")
    return SymbolFields(
        kind=kind.raw_value,
        present="true",
        defined_at=anchors.parse(exists.anchor_uri).path,
        anchor=exists.anchor_uri,
        is_deprecated=None if deprecated is None else deprecated.raw_value,
        namespace_closed=None if closed is None else closed.raw_value,
        signature_json=blob,
    )


def aspects_of(fields: SymbolFields) -> list[tuple[str, str]]:
    """The per-aspect code values a symbol's L1 fields stand for (the projector's read side).

    Returns:
        Sorted ``(aspect, value)`` pairs, excluding ``kind`` (not an aspect).
    """
    pairs: list[tuple[str, str]] = [("exists", fields.present)]
    if fields.is_deprecated is not None:
        pairs.append(("deprecated", fields.is_deprecated))
    if fields.namespace_closed is not None:
        pairs.append(("namespace_closed", fields.namespace_closed))
    if fields.signature_json is not None:
        pairs.extend(signature.to_claims(signature.from_json(fields.signature_json)))
    return sorted(pairs)
