"""Every row of ADR-0007's rule table, plus the abstentions that matter most."""

from __future__ import annotations

import pytest

from plumbline.domain.projection import SymbolState, is_projectable, project
from plumbline.domain.signature import ParamFacts, Signature

SIG = Signature(
    param_names=("host", "timeout", "*args"),
    params={"timeout": ParamFacts(default="30", type="None | int")},
    returns="str",
    raises=("KeyError",),
)
KWARGS_SIG = Signature(param_names=("host", "**options"))


def fn(sig: Signature | None = SIG, **kw: object) -> SymbolState:
    base = {"kind": "function", "present": True, "is_deprecated": False, "signature": sig}
    return SymbolState(**{**base, **kw})  # type: ignore[arg-type]


def module(*, closed: bool | None = True, present: bool | None = True) -> SymbolState:
    return SymbolState(kind="module", present=present, namespace_closed=closed)


def klass(*, closed: bool | None = True) -> SymbolState:
    return SymbolState(kind="class", present=True, namespace_closed=closed)


class TestParameterDetails:
    @pytest.mark.parametrize(
        ("aspect", "expected"),
        [
            ("param.timeout.default", "30"),
            ("param.timeout.type", "None | int"),
            ("param.timeout.exists", "true"),
            ("param.host.exists", "true"),
            ("returns.type", "str"),
        ],
    )
    def test_values_are_read_from_the_signature(self, aspect: str, expected: str) -> None:
        assert project(aspect, fn(), []) == expected

    @pytest.mark.parametrize("aspect", ["param.host.default", "param.host.type"])
    def test_a_value_the_importer_did_not_state_is_never_inferred(self, aspect: str) -> None:
        """No default and non-literal default look the same in the blob (ADR-0004)."""
        assert project(aspect, fn(), []) is None

    def test_a_missing_parameter_is_absent_without_kwargs(self) -> None:
        assert project("param.retries.exists", fn(), []) == "false"

    def test_but_not_provably_absent_when_kwargs_could_take_it(self) -> None:
        assert project("param.retries.exists", fn(KWARGS_SIG), []) is None
        assert project("param.host.exists", fn(KWARGS_SIG), []) == "true"

    def test_star_args_does_not_accept_keywords(self) -> None:
        """``*args`` takes positionals only, so a missing keyword is still absent."""
        assert project("param.retries.exists", fn(Signature(param_names=("*args",))), []) == "false"

    def test_a_default_or_type_for_a_missing_parameter_is_not_projected(self) -> None:
        assert project("param.retries.default", fn(), []) is None
        assert project("param.retries.type", fn(), []) is None

    def test_a_signature_with_unstated_names_abstains(self) -> None:
        assert project("param.host.exists", fn(Signature(returns="int")), []) is None


class TestRaises:
    def test_a_direct_raise_projects_true(self) -> None:
        assert project("raises.KeyError", fn(), []) == "true"

    def test_it_never_projects_false(self) -> None:
        """Absence of a raise cannot be proven (PRD R3)."""
        assert project("raises.TimeoutError", fn(), []) is None


class TestDeprecated:
    @pytest.mark.parametrize("kind", ["function", "method", "class"])
    @pytest.mark.parametrize("flag", [True, False])
    def test_the_static_marker_is_projected(self, kind: str, flag: bool) -> None:
        state = SymbolState(kind=kind, present=True, is_deprecated=flag)
        assert project("deprecated", state, []) == ("true" if flag else "false")

    @pytest.mark.parametrize(
        "state",
        [
            SymbolState(kind="ambiguous", present=True),
            SymbolState(kind="attribute", present=True, is_deprecated=False),
            SymbolState(kind="function", present=False, is_deprecated=False),
            SymbolState(),
        ],
    )
    def test_otherwise_it_abstains(self, state: SymbolState) -> None:
        assert project("deprecated", state, []) is None


class TestExists:
    def test_a_present_symbol_exists_even_in_an_open_namespace(self) -> None:
        assert project("exists", fn(), [module(closed=False)]) == "true"

    def test_an_ambiguous_symbol_certainly_exists(self) -> None:
        assert project("exists", SymbolState(kind="ambiguous", present=True), []) == "true"

    def test_a_removed_symbol_is_absent_in_a_closed_module(self) -> None:
        removed = SymbolState(kind="function", present=False)
        assert project("exists", removed, [module()]) == "false"

    def test_a_never_seen_symbol_is_absent_in_a_closed_module(self) -> None:
        assert project("exists", SymbolState(), [module()]) == "false"

    @pytest.mark.parametrize(
        "chain",
        [
            [module(closed=False)],  # __getattr__, star import, dynamic registration
            [module(closed=None)],  # closure never established
            [module(present=False)],  # the module itself is gone
            [],  # nothing known about where it would live
            [klass()],  # the chain never reached a module
            [klass(closed=False), module()],  # an open class under a closed module
            [klass(), module(closed=False)],  # a closed class under an open module
            [SymbolState(), module()],  # an unknown intermediate class
        ],
    )
    def test_absence_is_not_provable_unless_every_enclosing_namespace_is_closed(
        self, chain: list[SymbolState]
    ) -> None:
        assert project("exists", SymbolState(), chain) is None

    def test_a_member_of_a_closed_class_in_a_closed_module(self) -> None:
        assert project("exists", SymbolState(), [klass(), module()]) == "false"

    def test_a_symbol_known_but_without_a_verdict_is_not_called_absent(self) -> None:
        assert project("exists", SymbolState(kind="function"), [module()]) is None


class TestDetailsRequireAPresentCallable:
    @pytest.mark.parametrize(
        "state",
        [
            fn(present=False),
            fn(kind="class"),
            fn(kind="attribute"),
            fn(kind="ambiguous"),
            fn(None),  # decorated or otherwise unanalyzed: no signature stated
            SymbolState(),  # unseen
        ],
    )
    def test_every_detail_aspect_abstains(self, state: SymbolState) -> None:
        for aspect in (
            "param.timeout.default",
            "param.host.exists",
            "returns.type",
            "raises.KeyError",
        ):
            assert project(aspect, state, [module()]) is None


class TestScope:
    @pytest.mark.parametrize(
        ("aspect", "expected"),
        [
            ("exists", True), ("deprecated", True), ("returns.type", True),
            ("param.x.default", True), ("param.x.type", True), ("param.x.exists", True),
            ("raises.KeyError", True), ("raises.json.JSONDecodeError", True),
            ("param_names", False), ("added_in", False), ("removed_in", False),
            ("project.version", False), ("cli.serve.flag.port.exists", False),
            ("env.HOME.exists", False),
        ],
    )  # fmt: skip
    def test_only_the_aspects_this_projector_owns(self, aspect: str, expected: bool) -> None:
        assert is_projectable(aspect) is expected

    def test_an_unowned_aspect_projects_nothing(self) -> None:
        assert project("added_in", fn(), [module()]) is None


class TestFromFields:
    def test_an_unseen_or_stub_symbol_is_entirely_unknown(self) -> None:
        for fields in (None, {}):
            assert SymbolState.from_fields(fields) == SymbolState()

    def test_stored_fields_are_parsed(self) -> None:
        state = SymbolState.from_fields(
            {
                "kind": "function", "present": "true", "is_deprecated": "false",
                "defined_at": "src/m.py", "signature_json": '{"param_names":["a"],"v":1}',
            }
        )  # fmt: skip
        assert (state.kind, state.present, state.is_deprecated, state.defined_at) == (
            "function", True, False, "src/m.py",
        )  # fmt: skip
        assert state.signature is not None and state.signature.param_names == ("a",)
        assert state.namespace_closed is None  # not stated, so not "False"
