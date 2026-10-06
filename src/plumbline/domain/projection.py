"""What the code says, as a value for a doc claim to be compared with (PRD §7.4, ADR-0007).

The drift projector turns a symbol's L1 state into the value the code asserts for one
aspect, or into **nothing**. Abstention is the first-class output: a projection is only
produced when static analysis can *prove* it, because a wrong projection is a false
drift report, the one thing the product must not produce (PRD §3, principle 3).

The function here is pure -- it reads no KB and has no I/O -- so every row of the rule
table can be tested exhaustively. Gathering the state, finding the ancestors, and
writing the result are the application layer's job.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from plumbline.domain import canonical, signature
from plumbline.domain.signature import Signature

_PARAM_ASPECT = re.compile(
    r"^param\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)\.(?P<facet>exists|default|type)$"
)
_CALLABLES = frozenset({"function", "method"})
_DEPRECATABLE = frozenset({"function", "method", "class"})

PROJECTABLE_PREFIXES = ("param.", "raises.")
PROJECTABLE_EXACT = frozenset({"exists", "returns.type", "deprecated"})


def is_projectable(aspect: str) -> bool:
    """Whether this projector ever produces a value for ``aspect``.

    Other aspects (``added_in``, ``cli.*``, ``project.*``, ...) belong to other
    producers and are left alone.
    """
    if aspect in PROJECTABLE_EXACT:
        return True
    return aspect.startswith(PROJECTABLE_PREFIXES) and aspect != "param_names"


@dataclass(frozen=True, slots=True)
class SymbolState:
    """What L1 knows about one symbol. ``None`` always means "not known", never "no".

    Attributes:
        kind: ``module``, ``class``, ``function``, ``method``, ``attribute`` or
            ``ambiguous``; ``None`` if the KB has never seen the symbol.
        present: Whether the symbol is currently present, if known.
        is_deprecated: The static deprecation marker, if known.
        namespace_closed: Whether a module's or class's names are fully determined
            (ADR-0003), if known.
        signature: The parsed ``signature_json``, if the importer stated one.
        defined_at: The path of the definition, if known.
    """

    kind: str | None = None
    present: bool | None = None
    is_deprecated: bool | None = None
    namespace_closed: bool | None = None
    signature: Signature | None = None
    defined_at: str | None = None

    @classmethod
    def from_fields(cls, fields: Mapping[str, str] | None) -> SymbolState:
        """Build a state from the KB's stored ``Symbol`` fields (``None`` or ``{}`` = unseen)."""
        if not fields:
            return cls()
        blob = fields.get("signature_json")
        return cls(
            kind=fields.get("kind"),
            present=_flag(fields.get("present")),
            is_deprecated=_flag(fields.get("is_deprecated")),
            namespace_closed=_flag(fields.get("namespace_closed")),
            signature=None if blob is None else signature.from_json(blob),
            defined_at=fields.get("defined_at"),
        )


def _flag(value: str | None) -> bool | None:
    """``None`` stays unknown; otherwise the stored ``true``/``false`` string as a bool."""
    return None if value is None else value == "true"


def project(aspect: str, symbol: SymbolState, ancestors: Sequence[SymbolState]) -> str | None:
    """The value the code asserts for ``aspect`` of ``symbol``, or ``None`` to abstain.

    Args:
        aspect: A concrete aspect such as ``param.timeout.default``.
        symbol: The symbol's own state.
        ancestors: Its enclosing namespaces, nearest first, ending at the first
            enclosing *module*. Used only to decide whether absence is provable.

    Returns:
        A canonical value, or ``None`` if the analysis cannot be sure.
    """
    if aspect == "exists":
        return _exists(symbol, ancestors)
    if aspect == "deprecated":
        return _deprecated(symbol)
    if symbol.present is not True or symbol.kind not in _CALLABLES or symbol.signature is None:
        return None  # details are only ever read from a present function or method
    sig = symbol.signature
    if aspect == "returns.type":
        return sig.returns
    if aspect.startswith("raises."):
        return "true" if aspect.removeprefix("raises.") in sig.raises else None  # never "false"
    match = _PARAM_ASPECT.match(aspect)
    if match is None or sig.param_names is None:
        return None
    return _parameter(match["name"], match["facet"], sig, sig.param_names)


def _exists(symbol: SymbolState, ancestors: Sequence[SymbolState]) -> str | None:
    """``true`` if present; ``false`` only when every enclosing namespace is closed."""
    if symbol.present is True:
        return canonical.canonical_bool(True)  # an ambiguous symbol still certainly exists
    if symbol.present is None and symbol.kind is not None:
        return None  # known to the KB but with no verdict: not provably absent
    # Removed, or never seen: absent only if nothing could still supply the name.
    if not ancestors or ancestors[-1].kind != "module":
        return None  # the chain never reached a module we know about
    if all(a.present is True and a.namespace_closed is True for a in ancestors):
        return canonical.canonical_bool(False)
    return None


def _deprecated(symbol: SymbolState) -> str | None:
    """The static deprecation marker, for a present function, method, or class."""
    if symbol.present is True and symbol.kind in _DEPRECATABLE and symbol.is_deprecated is not None:
        return canonical.canonical_bool(symbol.is_deprecated)
    return None


def _parameter(name: str, facet: str, sig: Signature, names: tuple[str, ...]) -> str | None:
    """``exists``, ``default`` or ``type`` of one named parameter, or ``None`` to abstain."""
    named = signature.named_params(names)
    if facet == "exists":
        # A parameter documented by its bare name may be declared `*name` or `**name`.
        if name in named or name in {n.lstrip("*") for n in names if n.startswith("*")}:
            return canonical.canonical_bool(True)
        # `**kwargs` can accept any keyword and `*args` any positional: a documented name that is
        # not declared may be what they receive, so its absence is not provable (Amendment 6 A).
        if any(n.startswith("*") for n in names):
            return None
        return canonical.canonical_bool(False)
    if name not in named:
        return None  # a default or type for a parameter that is not there: exists is the drift
    facts = sig.params.get(name)
    if facts is None:
        return None  # no default / no annotation stated: never inferred (ADR-0004)
    return facts.default if facet == "default" else facts.type
