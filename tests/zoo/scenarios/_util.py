"""Small helpers shared by the scenario modules."""

from __future__ import annotations

import textwrap


def text(block: str) -> str:
    """Dedent a triple-quoted block and drop its leading newline."""
    return textwrap.dedent(block).lstrip("\n")


def package(scenario_id: str) -> dict[str, str]:
    """The package marker every scenario ships, so its modules are importable-looking."""
    return {f"src/{scenario_id}/__init__.py": f'"""{scenario_id}."""\n'}


def sym(scenario_id: str, dotted: str) -> str:
    """The qualified symbol key for ``<scenario_id>.<dotted>``."""
    return f"py:{scenario_id}.{dotted}"
