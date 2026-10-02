"""The canonical ``signature_json`` blob (ADR-0004)."""

from __future__ import annotations

import pytest

from plumbline.domain import signature
from plumbline.domain.signature import ParamFacts, Signature

FULL = Signature(
    param_names=("host", "timeout", "**opts"),
    params={"timeout": ParamFacts(default="30", type="None | int")},
    returns="str",
    raises=("KeyError", "json.JSONDecodeError"),
)


class TestJson:
    def test_canonical_example(self) -> None:
        assert signature.to_json(FULL) == (
            '{"param_names":["host","timeout","**opts"],'
            '"params":{"timeout":{"default":"30","type":"None | int"}},'
            '"raises":["KeyError","json.JSONDecodeError"],"returns":"str","v":1}'
        )

    def test_round_trip(self) -> None:
        assert signature.from_json(signature.to_json(FULL)) == FULL

    def test_a_missing_default_differs_from_the_literal_none_default(self) -> None:
        """Abstention vs. a real `None` default (DRF-3)."""
        abstained = Signature(("x",), {"x": ParamFacts(type="int")})
        none_default = Signature(("x",), {"x": ParamFacts(default="None", type="int")})
        assert signature.to_json(abstained) != signature.to_json(none_default)
        assert "default" not in signature.to_json(abstained)

    def test_empty_signature_is_just_the_version(self) -> None:
        assert signature.to_json(Signature()) == '{"v":1}'

    def test_non_ascii_is_escaped_so_the_blob_is_stable(self) -> None:
        text = signature.to_json(Signature(returns="caf\u00e9"))
        assert text.isascii()
        assert signature.from_json(text).returns == "caf\u00e9"

    @pytest.mark.parametrize("text", ["[]", '{"v":2}', "{}", '{"v":1,"param_names":[1]}'])
    def test_rejects_other_shapes_and_versions(self, text: str) -> None:
        with pytest.raises(ValueError, match=r"version-1|list of strings"):
            signature.from_json(text)


class TestClaims:
    def test_to_claims_expands_the_blob(self) -> None:
        assert signature.to_claims(FULL) == sorted(
            [
                ("param_names", '["host","timeout","**opts"]'),
                ("param.host.exists", "true"),
                ("param.timeout.exists", "true"),
                ("param.timeout.default", "30"),
                ("param.timeout.type", "None | int"),
                ("returns.type", "str"),
                ("raises.KeyError", "true"),
                ("raises.json.JSONDecodeError", "true"),
            ]
        )

    def test_from_claims_inverts_to_claims(self) -> None:
        assert signature.from_claims(signature.to_claims(FULL)) == FULL

    def test_star_parameters_have_no_exists_fact(self) -> None:
        pairs = signature.to_claims(Signature(param_names=("*args", "**kw")))
        assert [a for a, _ in pairs] == ["param_names"]

    @pytest.mark.parametrize(
        ("pairs", "why"),
        [
            ([("exists", "true")], "not a signature aspect"),
            ([("param_names", "[]"), ("param_names", "[]")], "duplicate aspect"),
            ([("param.x.default", "1")], "without param_names"),
            ([("param_names", '["a"]')], "disagree"),  # a named param lacks its exists fact
            (
                [("param_names", '["a"]'), ("param.a.exists", "true"), ("param.b.exists", "true")],
                "disagree",
            ),
            ([("param_names", "{}")], "JSON list"),
        ],
    )
    def test_inconsistent_claims_are_rejected(self, pairs: list[tuple[str, str]], why: str) -> None:
        with pytest.raises(ValueError, match=why):
            signature.from_claims(pairs)

    def test_named_params_skips_star_forms(self) -> None:
        assert signature.named_params(["a", "*args", "b", "**kw"]) == ["a", "b"]
