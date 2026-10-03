"""A `RepoReader` over a real Git repository (PRD §7.7, ADR-0005).

Reads the tracked branch's **first-parent history**, oldest first, and file contents as of
any commit. It only ever runs read-only plumbing, with the user's and system's Git
configuration, hooks, and filesystem monitor switched off, so pointing it at someone
else's repository cannot run anything from it.

Three decisions here matter downstream:

* **Renames are not detected.** A rename is reported as the old path deleted and the new
  path added, which is what lets ingestion see the old symbols leave (ADR-0005).
* **Commit times are strictly increasing.** Valid time is the committer time clamped to be
  monotonic along first parent (PRD §7.7), because the KB refuses writes that move
  backwards and real history has out-of-order committer dates (rebases, clock skew).
* **A history window starts with a snapshot.** If ingestion starts at commit *N*, the KB
  has never seen the code that existed before it, so the first commit in the window is
  reported as touching every file in the tree.
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess  # nosec B404 -- the reader's whole job is to run git, with a fixed argv
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from plumbline.application.ports import CommitRef

DEFAULT_SUFFIXES = (".py", ".md", ".rst", ".toml")
"""Only these files can contain code facts or doc claims; the rest are never read."""

DEFAULT_EXCLUDE = (
    "tests/*", "test/*", "*/tests/*", "*/test/*", "conftest.py", "*/conftest.py",
    "build/*", "dist/*", ".venv/*", "venv/*", "node_modules/*", "*/node_modules/*",
    ".git/*", "*/__pycache__/*", "docs/_build/*",
)  # fmt: skip
"""Paths that are not the project's own documented surface (PRD ING-10)."""

_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
    "LC_ALL": "C",
}


def _git_executable() -> str:
    """The absolute path of ``git``, resolved at call time so a missing git is a clear error."""
    found = shutil.which("git")
    if found is None:
        raise GitError("git is not installed or not on PATH")
    return found


class GitError(RuntimeError):
    """Git failed in a way other than "that path does not exist at that commit"."""


class GitRepoReader:
    """Reads one repository's first-parent history and file contents.

    Args:
        repo: A path inside the repository (its working tree or a bare repository).
        branch: The tracked branch; ``HEAD`` if omitted.
        suffixes: Only paths ending in one of these are reported or read.
        exclude: ``fnmatch`` patterns (where ``*`` also matches ``/``) for paths to ignore.
    """

    def __init__(
        self,
        repo: Path,
        *,
        branch: str | None = None,
        suffixes: Sequence[str] = DEFAULT_SUFFIXES,
        exclude: Sequence[str] = DEFAULT_EXCLUDE,
    ) -> None:
        self._repo = Path(repo)
        self._branch = branch or "HEAD"
        self._suffixes = tuple(suffixes)
        self._exclude = tuple(exclude)

    def first_parent_history(self, *, since: datetime | None = None) -> list[CommitRef]:
        """Commits on the tracked branch's first-parent history, oldest first.

        With ``since``, the first commit at or after it carries every file in its tree as
        a changed path, so the knowledge base starts from a complete picture.
        """
        raw = self._git(
            "log", "--first-parent", "--reverse", "--format=%H%x09%P%x09%ct", self._branch
        )
        commits: list[tuple[str, str | None, datetime]] = []
        previous = datetime.min.replace(tzinfo=UTC)
        for line in raw.decode().splitlines():
            sha, parents, stamp = line.split("\t")
            when = datetime.fromtimestamp(int(stamp), tz=UTC)
            # Strictly increasing: equal times would give zero-length validity windows.
            when = max(when, previous + timedelta(microseconds=1))
            previous = when
            commits.append((sha, parents.split()[0] if parents else None, when))

        refs: list[CommitRef] = []
        snapshot_taken = since is None
        for sha, parent, when in commits:
            if since is not None and when < since:
                continue
            if not snapshot_taken:
                paths = self._tree(sha)
                snapshot_taken = True
            else:
                paths = self._changes(sha, parent)
            refs.append(CommitRef(sha, when, tuple(p for p in paths if self._relevant(p))))
        return refs

    def describe(self, sha: str) -> CommitRef:
        """One commit as the pipeline sees it: its time, and what it changed against its parent.

        Unlike `first_parent_history` it applies no monotonic clamp (that needs the commit
        before it), so it is for a commit already known to follow the last one ingested.
        """
        line = self._git("log", "-1", "--format=%H%x09%P%x09%ct", sha).decode().strip()
        full, parents, stamp = line.split("\t")
        paths = self._changes(full, parents.split()[0] if parents else None)
        when = datetime.fromtimestamp(int(stamp), tz=UTC)
        return CommitRef(full, when, tuple(p for p in paths if self._relevant(p)))

    def read_file_at(self, path: str, commit_sha: str) -> bytes:
        """The file's bytes after ``commit_sha``.

        Raises:
            FileNotFoundError: The path does not exist at that commit (it was deleted).
            GitError: Git failed for any other reason.
        """
        result = self._run("cat-file", "blob", f"{commit_sha}:{path}")
        if result.returncode == 0:
            return result.stdout
        # Git words "no such path" and "no such commit" alike, so check the commit: reading
        # a path from a commit that does not exist must never look like a deletion.
        if (
            self._run("rev-parse", "--verify", "--quiet", f"{commit_sha}^{{commit}}").returncode
            == 0
        ):
            raise FileNotFoundError(path)
        raise GitError(f"no such commit: {commit_sha}")

    def _relevant(self, path: str) -> bool:
        return path.endswith(self._suffixes) and not any(
            fnmatch.fnmatchcase(path, pattern) for pattern in self._exclude
        )

    def _tree(self, sha: str) -> list[str]:
        raw = self._git("ls-tree", "-r", "--name-only", "-z", sha)
        return [p for p in raw.decode().split("\0") if p]

    def _changes(self, sha: str, parent: str | None) -> list[str]:
        """Added, modified, and deleted paths against the first parent, with no rename detection."""
        args = ["diff-tree", "-r", "--no-renames", "--name-only", "-z", "--no-commit-id"]
        raw = self._git(*args, *(["--root"] if parent is None else [parent]), sha)
        return [p for p in raw.decode().split("\0") if p]

    def _run(self, *args: str) -> subprocess.CompletedProcess[bytes]:
        hardening = [
            "-c", "core.quotepath=off",
            "-c", "core.fsmonitor=false",
            "-c", f"core.hooksPath={os.devnull}",
        ]  # fmt: skip
        # A fixed argument list, run without a shell: paths and SHAs are single argv entries
        # that are never interpreted, so nothing inside a repository can inject a command.
        return subprocess.run(  # nosec B603 B607 -- fixed argv, absolute git, no shell
            [_git_executable(), "-C", str(self._repo), *hardening, *args],
            capture_output=True,
            env={"PATH": os.environ.get("PATH", ""), "HOME": os.devnull, **_ENV},
            check=False,
        )

    def _git(self, *args: str) -> bytes:
        result = self._run(*args)
        if result.returncode != 0:
            raise GitError(
                f"git {' '.join(args[:2])}: {result.stderr.decode(errors='replace').strip()}"
            )
        return result.stdout


def repo_slug(repo: Path) -> str:
    """``owner/name`` from the ``origin`` remote, else ``local/<directory name>``."""
    result = subprocess.run(  # nosec B603 B607 -- fixed argv, absolute git, no shell
        [_git_executable(), "-C", str(repo), "remote", "get-url", "origin"],
        capture_output=True,
        env={"PATH": os.environ.get("PATH", ""), "HOME": os.devnull, **_ENV},
        check=False,
    )
    url = result.stdout.decode().strip()
    if result.returncode == 0 and url:
        tail = url.removesuffix(".git").replace(":", "/").split("/")
        if len(tail) >= 2 and tail[-1] and tail[-2]:
            return f"{tail[-2]}/{tail[-1]}"
    return f"local/{Path(repo).resolve().name}"
