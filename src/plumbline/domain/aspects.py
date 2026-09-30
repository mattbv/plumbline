"""The 1.0 aspect catalog (PRD §7.4).

An "aspect" is a checkable facet of a `Symbol` — atomic, because docs rarely
state whole signatures ("there's a `timeout` kwarg", not the full parameter
list). One aspect per fact means a partial claim hits exactly the slot it
speaks to, which is what keeps `Fact.value` equality comparison meaningful.

Each `Aspect` names its own canonical value shape; the actual canonicalizer
functions live in `plumbline.domain.canonical`, kept separate so the catalog
itself (what's checkable) stays independent of how a given value is
normalized (which may change — a canonicalizer version bump triggers a
re-projection pass, PRD §7.4/ING-5).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ValueShape(Enum):
    """The kind of value an aspect's canonical form takes."""

    BOOLEAN = "boolean"
    TEXT = "text"
    VERSION = "version"


@dataclass(frozen=True, slots=True)
class Aspect:
    """One entry in the catalog: a checkable facet, and whether it's drift-capable.

    Attributes:
        name: The suffix after `#` in a Fact's natural key, e.g. "exists" or
            "param.<p>.default" (the literal `<p>` is filled in per-parameter
            at extraction time — this catalog entry describes the *shape*).
        value_shape: What kind of canonical value this aspect holds.
        drift_capable: False for "corroboration only" aspects (PRD §7.4) —
            `raises.<Exc>` can prove presence but never absence, so a
            disagreement there can never be asserted as drift, only as an
            unverified/verified split.
        description: One line, for `plumb explain`'s own output and docs.
    """

    name: str
    value_shape: ValueShape
    drift_capable: bool
    description: str


# The catalog itself (PRD §7.4's table). `param.<p>.*` and `cli.<cmd>.flag.<f>.*`
# entries are templates — a real Fact's aspect substitutes the parameter/flag
# name, so this catalog names the *pattern*, not a fixed list of parameters.
CATALOG: tuple[Aspect, ...] = (
    Aspect("exists", ValueShape.BOOLEAN, True, "The symbol is defined and resolvable."),
    Aspect("param_names", ValueShape.TEXT, True, "Canonical ordered parameter name list."),
    Aspect("param.<p>.exists", ValueShape.BOOLEAN, True, "Parameter <p> is present."),
    Aspect("param.<p>.default", ValueShape.TEXT, True, "Parameter <p>'s default value."),
    Aspect("param.<p>.type", ValueShape.TEXT, True, "Parameter <p>'s annotated type."),
    Aspect("returns.type", ValueShape.TEXT, True, "The return annotation."),
    Aspect(
        "raises.<Exc>",
        ValueShape.BOOLEAN,
        False,
        "<Exc> can be raised. Corroboration only -- absence can't be proven.",
    ),
    Aspect("deprecated", ValueShape.BOOLEAN, True, "The symbol is marked deprecated."),
    Aspect("added_in", ValueShape.VERSION, True, "The release that introduced the symbol."),
    Aspect("removed_in", ValueShape.VERSION, True, "The release that removed the symbol."),
    Aspect("cli.<cmd>.flag.<f>.exists", ValueShape.BOOLEAN, True, "CLI flag <f> exists on <cmd>."),
    Aspect("env.<VAR>.exists", ValueShape.BOOLEAN, True, "Environment variable <VAR> is read."),
    Aspect("project.version", ValueShape.VERSION, True, "The project's own released version."),
    Aspect("project.requires_python", ValueShape.TEXT, True, "The project's Python version floor."),
)

_BY_NAME: dict[str, Aspect] = {aspect.name: aspect for aspect in CATALOG}


def get(name: str) -> Aspect:
    """Look up a catalog entry by its literal or templated name.

    Args:
        name: Either a fixed name (e.g. "exists") or, for a templated aspect,
            the name with its placeholder still literal (e.g. "param.<p>.default")
            -- callers substituting a real parameter name should look up the
            template, not the substituted string.

    Returns:
        The matching `Aspect`.

    Raises:
        KeyError: No catalog entry has this name.
    """
    return _BY_NAME[name]
