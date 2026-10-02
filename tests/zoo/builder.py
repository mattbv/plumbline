"""Materialize scenarios as one real, byte-for-byte reproducible Git repository.

Everything that could leak into a commit SHA is pinned: author/committer
identity and timestamps, the user's and system's Git config (ignored), hooks,
line-ending conversion, and the order in which files and scenarios are written.
Building the same scenarios twice therefore yields identical SHAs -- the M0
exit criterion's "deterministic across two runs" starts here.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .model import Scenario

EPOCH = datetime(2024, 1, 1, tzinfo=UTC)
"""Commit 0's time. Each later commit lands one hour after the previous one."""

COMMIT_SPACING = timedelta(hours=1)
_IDENTITY = ("Zoo Author", "zoo@example.invalid")


@dataclass(frozen=True, slots=True)
class BuiltZoo:
    """The result of `build`.

    Attributes:
        root: The repository's working directory.
        shas: ``(scenario id, commit label)`` -> the commit's SHA.
        committed_at: ``(scenario id, commit label)`` -> the commit's time.
    """

    root: Path
    shas: dict[tuple[str, str], str]
    committed_at: dict[tuple[str, str], datetime]

    def head_tree(self) -> str:
        """Return the tree hash of HEAD (identical trees hash identically)."""
        return _git(self.root, {}, "rev-parse", "HEAD^{tree}").strip()


def _git(root: Path, extra_env: dict[str, str], *args: str) -> str:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(root),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
        **extra_env,
    }
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.autocrlf=false",
            "-c",
            "core.hooksPath=" + os.devnull,
            "-c",
            "commit.gpgsign=false",
            "-c",
            "tag.gpgsign=false",
            "-c",
            "core.fsmonitor=false",
            *args,
        ],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def timeline(scenarios: Sequence[Scenario]) -> dict[tuple[str, str], datetime]:
    """Commit time of every ``(scenario id, commit label)``: one hour apart, in id order."""
    times: dict[tuple[str, str], datetime] = {}
    for scenario in sorted(scenarios, key=lambda s: s.id):
        for commit in scenario.commits:
            times[(scenario.id, commit.label)] = EPOCH + len(times) * COMMIT_SPACING
    return times


def tag_name(scenario_id: str, version: str) -> str:
    """Return the release tag created for `version` in scenario `scenario_id`."""
    return f"{scenario_id}/v{version}"


def build(scenarios: Sequence[Scenario], dest: Path) -> BuiltZoo:
    """Build `scenarios` into a fresh Git repository at `dest`.

    Scenarios are applied in id order; each lives under ``scenarios/<id>/`` so
    their symbols, READMEs and changelogs never collide.

    Args:
        scenarios: The scenarios to materialize.
        dest: An empty (or non-existent) directory to create the repo in.

    Returns:
        The built repository's location and per-commit SHAs and times.

    Raises:
        ValueError: Two scenarios share an id.
    """
    ordered = sorted(scenarios, key=lambda s: s.id)
    ids = [s.id for s in ordered]
    if len(ids) != len(set(ids)):
        raise ValueError("scenario ids must be unique")

    dest.mkdir(parents=True, exist_ok=True)
    _git(dest, {}, "init", "-q", "-b", "main")

    shas: dict[tuple[str, str], str] = {}
    times = timeline(ordered)
    for scenario in ordered:
        for commit in scenario.commits:
            base = dest / "scenarios" / scenario.id
            for rel in commit.delete:
                (base / rel).unlink()
            for rel in sorted(commit.write):
                target = base / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(commit.write[rel].encode("utf-8"))

            when = times[(scenario.id, commit.label)]
            stamp = when.strftime("%Y-%m-%dT%H:%M:%S+0000")
            env = {
                "GIT_AUTHOR_NAME": _IDENTITY[0],
                "GIT_AUTHOR_EMAIL": _IDENTITY[1],
                "GIT_AUTHOR_DATE": stamp,
                "GIT_COMMITTER_NAME": _IDENTITY[0],
                "GIT_COMMITTER_EMAIL": _IDENTITY[1],
                "GIT_COMMITTER_DATE": stamp,
            }
            _git(dest, env, "add", "-A")
            _git(dest, env, "commit", "-q", "--no-verify", "--allow-empty", "-m", commit.message)
            sha = _git(dest, {}, "rev-parse", "HEAD").strip()
            if commit.tag is not None:
                _git(dest, env, "tag", tag_name(scenario.id, commit.tag))
            shas[(scenario.id, commit.label)] = sha
    return BuiltZoo(root=dest, shas=shas, committed_at=times)
