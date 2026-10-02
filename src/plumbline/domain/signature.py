"""The canonical ``Symbol.signature_json`` blob and its inverse (ADR-0004).

One symbol's calling/raising facts -- parameter names, per-parameter default
and type, return type, and directly raised exceptions -- live in a single
canonical JSON object, so a symbol's whole signature is one coherent
``time_varying`` assertion that ``as_of(t)`` returns intact.

**A missing key means the importer abstained; it never means "none".** A
non-literal default has no ``"default"`` entry, which is different from the
literal default ``"None"``. That keeps abstention (PRD DRF-3) intact end to end.

The module is pure: it knows aspect names and canonical value strings, nothing
about claims, Git, or Ontolith. `to_claims` / `from_claims` convert between a
`Signature` and the importer's ``(aspect, value)`` pairs; `to_json` /
`from_json` convert to and from the stored blob. The serialization is part of
the contract, so it is versioned (`SIGNATURE_VERSION`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from plumbline.domain import canonical

SIGNATURE_VERSION = 1

_PARAM_ASPECT = re.compile(
    r"^param\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)\.(?P<facet>exists|default|type)$"
)
_RAISES_PREFIX = "raises."


@dataclass(frozen=True, slots=True)
class ParamFacts:
    """What the importer established about one named parameter (``None`` = abstained)."""

    default: str | None = None
    type: str | None = None


@dataclass(frozen=True, slots=True)
class Signature:
    """Everything the importer extracted about one function or method's signature.

    Attributes:
        param_names: Canonical ordered names, ``*args``/``**kwargs`` rendered
            with their stars; ``None`` if not established.
        params: Facts per *named* parameter that has any (absent = nothing known).
        returns: Canonical return annotation, if annotated.
        raises: Sorted exception names raised directly in the body.
    """

    param_names: tuple[str, ...] | None = None
    params: Mapping[str, ParamFacts] = field(default_factory=dict)
    returns: str | None = None
    raises: tuple[str, ...] = ()


def named_params(param_names: Iterable[str]) -> list[str]:
    """The parameters that are plain names (not ``*args`` / ``**kwargs``), in order."""
    return [name for name in param_names if not name.startswith("*")]


def to_json(signature: Signature) -> str:
    """Serialize to the canonical blob: sorted keys, compact separators, ASCII only."""
    body: dict[str, object] = {"v": SIGNATURE_VERSION}
    if signature.param_names is not None:
        body["param_names"] = list(signature.param_names)
    params = {
        name: {k: v for k, v in (("default", f.default), ("type", f.type)) if v is not None}
        for name, f in sorted(signature.params.items())
        if f.default is not None or f.type is not None
    }
    if params:
        body["params"] = params
    if signature.returns is not None:
        body["returns"] = signature.returns
    if signature.raises:
        body["raises"] = sorted(signature.raises)
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def from_json(text: str) -> Signature:
    """Parse a stored blob.

    Raises:
        ValueError: Not a version-1 blob of the expected shape.
    """
    body = json.loads(text)
    if not isinstance(body, dict) or body.get("v") != SIGNATURE_VERSION:
        raise ValueError(f"not a version-{SIGNATURE_VERSION} signature blob")
    names = body.get("param_names")
    if names is not None and not (
        isinstance(names, list) and all(isinstance(n, str) for n in names)
    ):
        raise ValueError("param_names must be a list of strings")
    params = {
        name: ParamFacts(default=facts.get("default"), type=facts.get("type"))
        for name, facts in body.get("params", {}).items()
    }
    return Signature(
        param_names=None if names is None else tuple(names),
        params=params,
        returns=body.get("returns"),
        raises=tuple(body.get("raises", ())),
    )


def to_claims(signature: Signature) -> list[tuple[str, str]]:
    """The importer-style ``(aspect, value)`` pairs a `Signature` stands for, sorted."""
    pairs: list[tuple[str, str]] = []
    if signature.param_names is not None:
        pairs.append(("param_names", canonical.canonical_param_names(signature.param_names)))
        pairs.extend(
            (f"param.{name}.exists", "true") for name in named_params(signature.param_names)
        )
    for name, facts in signature.params.items():
        if facts.default is not None:
            pairs.append((f"param.{name}.default", facts.default))
        if facts.type is not None:
            pairs.append((f"param.{name}.type", facts.type))
    if signature.returns is not None:
        pairs.append(("returns.type", signature.returns))
    pairs.extend((f"{_RAISES_PREFIX}{exc}", "true") for exc in signature.raises)
    return sorted(pairs)


def from_claims(pairs: Iterable[tuple[str, str]]) -> Signature:
    """Build a `Signature` from ``(aspect, value)`` pairs.

    Raises:
        ValueError: An aspect is not a signature aspect, an aspect repeats, or
            the per-parameter facts are inconsistent with ``param_names``.
    """
    seen: set[str] = set()
    param_names: tuple[str, ...] | None = None
    exists: set[str] = set()
    defaults: dict[str, str] = {}
    types: dict[str, str] = {}
    returns: str | None = None
    raises: set[str] = set()

    for aspect, value in pairs:
        if aspect in seen:
            raise ValueError(f"duplicate aspect {aspect!r}")
        seen.add(aspect)
        match = _PARAM_ASPECT.match(aspect)
        if aspect == "param_names":
            names = json.loads(value)
            if not (isinstance(names, list) and all(isinstance(n, str) for n in names)):
                raise ValueError("param_names must be a JSON list of strings")
            param_names = tuple(names)
        elif match is not None:
            facet, name = match["facet"], match["name"]
            if facet == "exists":
                exists.add(name)
            elif facet == "default":
                defaults[name] = value
            else:
                types[name] = value
        elif aspect == "returns.type":
            returns = value
        elif aspect.startswith(_RAISES_PREFIX):
            raises.add(aspect.removeprefix(_RAISES_PREFIX))
        else:
            raise ValueError(f"not a signature aspect: {aspect!r}")

    mentioned = exists | defaults.keys() | types.keys()
    if param_names is None:
        if mentioned:
            raise ValueError("per-parameter facts without param_names")
    elif exists != set(named_params(param_names)) or not mentioned <= exists:
        raise ValueError("per-parameter facts disagree with param_names")

    params = {
        name: ParamFacts(default=defaults.get(name), type=types.get(name))
        for name in sorted(defaults.keys() | types.keys())
    }
    return Signature(param_names, params, returns, tuple(sorted(raises)))
