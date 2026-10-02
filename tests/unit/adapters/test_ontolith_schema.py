"""Structural guarantees of the compiled Plumbline schema (ADR-0001, ADR-0003)."""

from __future__ import annotations

import pytest

from plumbline.adapters.ontolith_schema import SCHEMA_VERSION, build_schema


@pytest.fixture(scope="module")
def symbol_properties() -> dict[str, dict[str, object]]:
    schema = build_schema().model_dump()
    return schema["concepts"]["Symbol"]["properties"]  # type: ignore[no-any-return]


def test_schema_compiles_at_the_version_a_fresh_kb_requires() -> None:
    """Ontolith only accepts version 1 on a fresh KB (monotonic versions)."""
    assert SCHEMA_VERSION == 1
    assert build_schema().version == 1


def test_every_symbol_fact_but_kind_is_time_varying(
    symbol_properties: dict[str, dict[str, object]],
) -> None:
    """L1 is code history: code changing is expected, so it supersedes (ADR-0001)."""
    static = {n for n, p in symbol_properties.items() if p["temporality"] == "static"}
    assert static == {"kind"}


def test_namespace_closed_is_an_optional_boolean(
    symbol_properties: dict[str, dict[str, object]],
) -> None:
    """Optional because functions and methods have no member namespace (ADR-0003)."""
    prop = symbol_properties["namespace_closed"]
    assert prop["value_type"] == "Boolean"
    assert prop["required"] is False
    assert prop["temporality"] == "time_varying"
    assert prop["cardinality"] == "single"


def test_other_symbol_facts_stay_required(symbol_properties: dict[str, dict[str, object]]) -> None:
    for name in ("kind", "defined_at", "signature_json", "is_deprecated", "present"):
        assert symbol_properties[name]["required"] is True
