"""Properties the projection rules must hold for *every* symbol state (PRD §3 principle 3).

The rule table is pure, so rather than sample it we ask it the one question that
matters: could any combination of symbol state and ancestry make it assert something
it should not? A projection that is wrong is a false drift report.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from plumbline.domain.projection import SymbolState, is_projectable, project
from plumbline.domain.signature import ParamFacts, Signature
from tests.zoo.oracle import resolve_aspect, value_problem

_name = st.from_regex(r"[a-z][a-z0-9_]{0,5}", fullmatch=True)
_flag = st.none() | st.booleans()
_kinds = st.none() | st.sampled_from(
    ["module", "class", "function", "method", "attribute", "ambiguous"]
)


@st.composite
def signatures(draw: st.DrawFn) -> Signature | None:
    if draw(st.booleans()):
        return None
    plain = draw(st.lists(_name, unique=True, max_size=3))
    names = list(plain)
    if draw(st.booleans()):
        names.append("**" + draw(_name))
    params = {
        n: ParamFacts(draw(st.none() | st.integers().map(str)), draw(st.none() | st.just("int")))
        for n in plain
    }
    return Signature(
        tuple(names) if draw(st.booleans()) else None,
        params,
        draw(st.none() | st.just("str")),
        tuple(sorted(draw(st.sets(st.sampled_from(["KeyError", "ValueError"]), max_size=2)))),
    )


states = st.builds(
    SymbolState,
    kind=_kinds,
    present=_flag,
    is_deprecated=_flag,
    namespace_closed=_flag,
    signature=signatures(),
    defined_at=st.none() | st.just("src/m.py"),
)
chains = st.lists(states, max_size=4)
aspects = st.sampled_from(
    ["exists", "deprecated", "returns.type", "raises.KeyError", "raises.ValueError"]
) | _name.flatmap(
    lambda p: st.sampled_from([f"param.{p}.exists", f"param.{p}.default", f"param.{p}.type"])
)


@given(aspects, states, chains)
def test_it_never_raises_and_only_ever_returns_canonical_values(
    aspect: str, symbol: SymbolState, ancestors: list[SymbolState]
) -> None:
    value = project(aspect, symbol, ancestors)
    if value is not None:
        catalog = resolve_aspect(aspect)
        assert catalog is not None
        assert value_problem(catalog, value) is None


@given(states, chains, _name)
def test_absence_is_only_asserted_where_every_enclosing_namespace_is_provably_closed(
    symbol: SymbolState, ancestors: list[SymbolState], name: str
) -> None:
    if project("exists", symbol, ancestors) != "false":
        return
    assert symbol.present is not True
    assert ancestors and ancestors[-1].kind == "module"
    assert all(a.present is True and a.namespace_closed is True for a in ancestors)


@given(states, chains, _name)
def test_a_present_symbol_is_never_called_absent(
    symbol: SymbolState, ancestors: list[SymbolState], name: str
) -> None:
    if symbol.present is True:
        assert project("exists", symbol, ancestors) == "true"


@given(states, chains, st.sampled_from(["KeyError", "ValueError", "TimeoutError"]))
def test_a_raise_is_never_projected_false(
    symbol: SymbolState, ancestors: list[SymbolState], exc: str
) -> None:
    assert project(f"raises.{exc}", symbol, ancestors) in (None, "true")


@given(states, chains, _name)
def test_a_missing_parameter_is_never_absent_when_kwargs_could_take_it(
    symbol: SymbolState, ancestors: list[SymbolState], name: str
) -> None:
    value = project(f"param.{name}.exists", symbol, ancestors)
    if value == "false":
        names = symbol.signature.param_names if symbol.signature else None
        assert names is not None
        assert not any(n.startswith("**") for n in names)
        assert name not in [n for n in names if not n.startswith("*")]


@given(aspects, states, chains)
def test_details_are_never_projected_for_anything_but_a_present_callable(
    aspect: str, symbol: SymbolState, ancestors: list[SymbolState]
) -> None:
    if aspect in ("exists", "deprecated"):
        return
    if project(aspect, symbol, ancestors) is not None:
        assert symbol.present is True and symbol.kind in ("function", "method")
        assert symbol.signature is not None


@given(aspects, states, chains)
def test_it_only_speaks_for_aspects_it_owns(
    aspect: str, symbol: SymbolState, ancestors: list[SymbolState]
) -> None:
    if project(aspect, symbol, ancestors) is not None:
        assert is_projectable(aspect)
