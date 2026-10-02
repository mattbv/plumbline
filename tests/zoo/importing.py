"""Run the code importer over a scenario's files at a given commit."""

from __future__ import annotations

from datetime import UTC, datetime

from plumbline.adapters.python_code_importer import PythonCodeImporter
from plumbline.application.ports import CommitRef, RawClaim

from .model import Scenario

_SHA = "abcdef0" * 5 + "abcde"


def claims_at(scenario: Scenario, label: str) -> list[RawClaim]:
    """Everything the importer emits for the scenario's whole tree after commit `label`."""
    files = {
        f"scenarios/{scenario.id}/{path}": text.encode()
        for path, text in scenario.files_at(label).items()
    }
    commit = CommitRef(_SHA, datetime(2024, 1, 1, tzinfo=UTC), ())
    return PythonCodeImporter("zoo", "zoo").extract(files, commit)
