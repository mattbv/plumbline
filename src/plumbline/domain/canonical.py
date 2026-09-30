"""Canonicalization: the product's precision engine (PRD §7.4).

Drift detection is exact-equality comparison on `Fact.value` -- so two
sources that mean the same thing must produce the *same string*, or every
canonicalization gap becomes a false-positive contradiction (Risk R1 in the
PRD). Each function here is pure, deterministic, and versioned via
`CANONICALIZER_VERSION`: bumping it is a visible, auditable event that
should trigger a re-projection pass (ING-5), never a silent behavior change.
"""

from __future__ import annotations

import ast
import re

CANONICALIZER_VERSION = "1"

_PEP604_UNION = re.compile(r"\s*\|\s*")
_WHITESPACE = re.compile(r"\s+")


def canonical_bool(value: bool) -> str:
    """Canonical form of a boolean aspect value: the literal "true"/"false"."""
    return "true" if value else "false"


def canonical_literal(value: str) -> str | None:
    """Canonical form of a Python literal default (PRD's `param.<p>.default`).

    Args:
        value: Source text of the default expression, e.g. "30" or "'utf-8'".

    Returns:
        `repr()` of the parsed literal, or `None` if the projector should
        abstain -- the expression isn't a literal `ast.literal_eval` can
        evaluate (e.g. it references another name), so no canonical
        projection can be asserted at all (never guess).
    """
    try:
        parsed = ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return None
    return repr(parsed)


def canonical_type_annotation(annotation: str) -> str:
    """Canonical form of a type annotation string.

    Normalizes PEP 604 unions to a fixed member order and collapses
    incidental whitespace, so `int | None` and `None | int` (and
    `Optional[int]`'s own textual variants, once the extractor normalizes
    to `|` first) compare equal.
    """
    collapsed = _WHITESPACE.sub(" ", annotation.strip())
    if "|" in collapsed:
        members = sorted(m.strip() for m in _PEP604_UNION.split(collapsed))
        return " | ".join(members)
    return collapsed


def canonical_version(version: str) -> str | None:
    """Canonical form of a PEP 440-ish version string.

    Returns:
        The trimmed version string, or `None` if it doesn't look like a
        version at all (abstain rather than assert something wrong).
    """
    trimmed = version.strip()
    if not re.match(r"^v?\d+(\.\d+)*([.\-\+][0-9A-Za-z.]+)?$", trimmed):
        return None
    return trimmed.removeprefix("v")
