"""Run the code importer over a scenario's files at a given commit."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from plumbline.adapters.python_code_importer import PythonCodeImporter
from plumbline.application.ports import CommitRef, RawClaim

from .builder import timeline
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


@dataclass(frozen=True, slots=True)
class ZooStep:
    """One commit of one scenario, as the ingestion pipeline sees it."""

    scenario: Scenario
    label: str
    ref: CommitRef


class ZooHistory:
    """The whole zoo as a single linear history, with a `RepoReader` over it.

    Commit order and times match `builder.build`, so a KB ingested from here
    lines up with the real Git repository the builder produces. SHAs are
    synthetic (the position, hex-encoded): the pipeline only treats them as
    opaque anchors.
    """

    def __init__(self, scenarios: Sequence[Scenario]) -> None:
        times = timeline(scenarios)
        self.steps: list[ZooStep] = []
        self._at: dict[str, tuple[Scenario, str]] = {}
        for scenario in sorted(scenarios, key=lambda s: s.id):
            for commit in scenario.commits:
                sha = f"{len(self.steps) + 1:040x}"
                touched = (*commit.write, *commit.delete)
                ref = CommitRef(
                    sha=sha,
                    committed_at=times[(scenario.id, commit.label)],
                    changed_paths=tuple(f"scenarios/{scenario.id}/{p}" for p in sorted(touched)),
                )
                self.steps.append(ZooStep(scenario, commit.label, ref))
                self._at[sha] = (scenario, commit.label)

    def first_parent_history(self, *, since: datetime | None = None) -> list[CommitRef]:
        """All commits, oldest first."""
        return [step.ref for step in self.steps if since is None or step.ref.committed_at >= since]

    def read_file_at(self, path: str, commit_sha: str) -> bytes:
        """The file's bytes after that commit; `FileNotFoundError` if it does not exist then."""
        scenario, label = self._at[commit_sha]
        prefix = f"scenarios/{scenario.id}/"
        relative = path.removeprefix(prefix)
        files = scenario.files_at(label)
        if not path.startswith(prefix) or relative not in files:
            raise FileNotFoundError(path)
        return files[relative].encode()
