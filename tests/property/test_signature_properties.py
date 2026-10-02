"""The signature blob and the assembler are exact inverses (ADR-0004, PRD §9.4)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from plumbline.application.ports import RawClaim
from plumbline.application.symbol_facts import aspects_of, assemble
from plumbline.domain import signature
from plumbline.domain.signature import ParamFacts, Signature

_ident = st.from_regex(r"[a-z][a-z0-9_]{0,6}", fullmatch=True)
_value = st.text(max_size=12)
_exc = st.lists(_ident, min_size=1, max_size=2).map(".".join)


@st.composite
def signatures(draw: st.DrawFn) -> Signature:
    plain = draw(st.lists(_ident, unique=True, max_size=4))
    names = list(plain)
    if draw(st.booleans()):
        names.append("*" + draw(_ident))
    if draw(st.booleans()):
        names.append("**" + draw(_ident))
    params: dict[str, ParamFacts] = {}
    for name in plain:
        default, type_ = draw(st.none() | _value), draw(st.none() | _value)
        if default is not None or type_ is not None:
            params[name] = ParamFacts(default, type_)
    return Signature(
        param_names=tuple(names),
        params=params,
        returns=draw(st.none() | _value),
        raises=tuple(sorted(draw(st.sets(_exc, max_size=3)))),
    )


@given(signatures())
def test_json_round_trips(sig: Signature) -> None:
    assert signature.from_json(signature.to_json(sig)) == sig


@given(signatures())
def test_claims_round_trip(sig: Signature) -> None:
    assert signature.from_claims(signature.to_claims(sig)) == sig


@given(signatures())
def test_serialization_is_canonical(sig: Signature) -> None:
    """Equal signatures must serialize identically, or importers would churn writes."""
    blob = signature.to_json(sig)
    assert signature.to_json(signature.from_json(blob)) == blob
    assert blob.isascii()


@given(signatures())
def test_assembly_and_projection_are_inverses(sig: Signature) -> None:
    sha = "abcdef0123456789abcdef0123456789abcdef01"
    pairs = signature.to_claims(sig)
    claims = [
        RawClaim("py:p.m.f", aspect, value, f"repo://o/r@{sha}/src/p/m.py#L1-L2", 1.0, "t")
        for aspect, value in [
            ("exists", "true"),
            ("kind", "function"),
            ("deprecated", "false"),
            *pairs,
        ]
    ]
    fields = assemble(claims)["py:p.m.f"]
    expected = sorted([("exists", "true"), ("deprecated", "false"), *pairs])
    assert aspects_of(fields) == expected
