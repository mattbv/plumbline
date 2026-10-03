"""The Git `RepoReader` against real repositories (PRD §7.7, ADR-0005).

The drift zoo's builder produces a genuine, deterministic Git repository, so the reader is
checked against known answers: every commit, every changed and deleted path, every file.
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from plumbline.adapters.git_reader import DEFAULT_EXCLUDE, GitError, GitRepoReader, repo_slug
from tests.zoo import builder
from tests.zoo.scenarios import ALL

IDENT = {
    "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
}  # fmt: skip


def git(repo: Path, *args: str, when: str | None = None) -> str:
    env = {**os.environ, **IDENT}
    if when:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = when
    done = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=True
    )
    return done.stdout.strip()


def commit(repo: Path, message: str, files: dict[str, str | None], when: str | None = None) -> str:
    for rel, text in files.items():
        target = repo / rel
        if text is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", message, when=when)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    return tmp_path


@pytest.fixture(scope="module")
def zoo(tmp_path_factory: pytest.TempPathFactory) -> builder.BuiltZoo:
    return builder.build(ALL, tmp_path_factory.mktemp("zoo-git"))


class TestAgainstTheZooRepository:
    def test_every_commit_comes_back_in_order_with_its_time(self, zoo: builder.BuiltZoo) -> None:
        history = GitRepoReader(zoo.root).first_parent_history()
        assert [c.sha for c in history] == [
            zoo.shas[k] for k in sorted(zoo.shas, key=lambda k: zoo.committed_at[k])
        ]
        assert [c.committed_at for c in history] == sorted(zoo.committed_at.values())

    def test_changed_paths_are_exactly_what_the_commit_wrote_or_deleted(
        self, zoo: builder.BuiltZoo
    ) -> None:
        by_sha = {c.sha: c for c in GitRepoReader(zoo.root).first_parent_history()}
        scenario = next(s for s in ALL if s.id == "sig_change_docs_stale")
        c2 = by_sha[zoo.shas[("sig_change_docs_stale", "c2")]]
        assert c2.changed_paths == (
            "scenarios/sig_change_docs_stale/src/sig_change_docs_stale/client.py",
        )
        assert scenario.commits[1].write  # sanity: the scenario really does write one file

    def test_a_rename_is_a_deletion_plus_an_addition(self, zoo: builder.BuiltZoo) -> None:
        """Rename detection is off, so the old symbols are seen to leave (ADR-0005)."""
        by_sha = {c.sha: c for c in GitRepoReader(zoo.root).first_parent_history()}
        c2 = by_sha[zoo.shas[("file_renamed", "c2")]]
        base = "scenarios/file_renamed/src/file_renamed/"
        assert set(c2.changed_paths) == {f"{base}old.py", f"{base}new.py"}

    def test_file_contents_match_the_scenario_at_every_commit(self, zoo: builder.BuiltZoo) -> None:
        reader = GitRepoReader(zoo.root)
        scenario = next(s for s in ALL if s.id == "sig_change_docs_stale")
        path = "scenarios/sig_change_docs_stale/src/sig_change_docs_stale/client.py"
        for label in ("c1", "c2"):
            sha = zoo.shas[(scenario.id, label)]
            assert (
                reader.read_file_at(path, sha).decode()
                == scenario.files_at(label)["src/sig_change_docs_stale/client.py"]
            )

    def test_a_deleted_path_is_file_not_found(self, zoo: builder.BuiltZoo) -> None:
        sha = zoo.shas[("file_deleted", "c2")]
        with pytest.raises(FileNotFoundError):
            GitRepoReader(zoo.root).read_file_at(
                "scenarios/file_deleted/src/file_deleted/api.py", sha
            )

    def test_a_missing_commit_is_an_error_not_a_deletion(self, zoo: builder.BuiltZoo) -> None:
        """Misreading a bad SHA as 'the file was deleted' would silently remove symbols."""
        with pytest.raises(GitError, match="no such commit"):
            GitRepoReader(zoo.root).read_file_at("scenarios/x.py", "0" * 40)


class TestWhichPathsAreReported:
    def test_only_relevant_files_are_reported(self, repo: Path) -> None:
        commit(repo, "files", {
            "src/a.py": "x = 1\n", "README.md": "# r\n", "data.bin": "\x00", "notes.txt": "n",
            "tests/test_a.py": "def test(): ...\n", "conftest.py": "", "pkg/tests/t.py": "",
            "build/gen.py": "", "node_modules/x/y.py": "", "docs/guide.md": "g",
        })  # fmt: skip
        [only] = GitRepoReader(repo).first_parent_history()
        assert set(only.changed_paths) == {"src/a.py", "README.md", "docs/guide.md"}

    def test_suffixes_and_exclusions_are_configurable(self, repo: Path) -> None:
        commit(repo, "files", {"a.py": "", "b.rst": "", "tests/c.py": ""})
        [only] = GitRepoReader(repo, suffixes=(".rst",), exclude=()).first_parent_history()
        assert only.changed_paths == ("b.rst",)
        [everything] = GitRepoReader(repo, suffixes=(".py",), exclude=()).first_parent_history()
        assert set(everything.changed_paths) == {"a.py", "tests/c.py"}

    def test_unusual_path_names_survive(self, repo: Path) -> None:
        names = [
            "docs/my guide é.md",
            "src/a#b.py",
            "src/with space.py",
        ]  # no quotes: Windows forbids them
        commit(repo, "odd", dict.fromkeys(names, "x = 1\n"))
        [only] = GitRepoReader(repo).first_parent_history()
        assert set(only.changed_paths) == set(names)
        assert GitRepoReader(repo).read_file_at(names[0], only.sha) == b"x = 1\n"

    def test_the_defaults_cover_the_usual_noise(self) -> None:
        assert {"tests/*", "*/tests/*", "conftest.py", "node_modules/*"} <= set(DEFAULT_EXCLUDE)


class TestHistory:
    def test_the_root_commit_lists_everything_it_added(self, repo: Path) -> None:
        commit(repo, "root", {"a.py": "x = 1\n", "b.py": "y = 2\n"})
        [root] = GitRepoReader(repo).first_parent_history()
        assert set(root.changed_paths) == {"a.py", "b.py"}

    def test_a_commit_with_no_relevant_change_is_still_a_commit(self, repo: Path) -> None:
        commit(repo, "a", {"a.py": "x = 1\n"})
        commit(repo, "empty", {})
        commit(repo, "binary", {"data.bin": "1"})
        history = GitRepoReader(repo).first_parent_history()
        assert [c.changed_paths for c in history] == [("a.py",), (), ()]

    def test_commit_times_are_strictly_increasing_even_when_history_goes_backwards(
        self, repo: Path
    ) -> None:
        commit(repo, "1", {"a.py": "1"}, when="2024-03-01T12:00:00+0000")
        commit(repo, "2", {"a.py": "2"}, when="2024-01-01T12:00:00+0000")  # earlier: a skewed clock
        commit(
            repo, "3", {"a.py": "3"}, when="2024-03-01T12:00:00+0000"
        )  # an exact tie with commit 1
        times = [c.committed_at for c in GitRepoReader(repo).first_parent_history()]
        assert times == sorted(times) and len(set(times)) == 3
        assert times[1] - times[0] == timedelta(microseconds=1)

    def test_only_the_first_parent_line_is_followed(self, repo: Path) -> None:
        commit(repo, "base", {"a.py": "base\n"})
        git(repo, "switch", "-q", "-c", "feature")
        commit(repo, "feature 1", {"feature.py": "1\n"})
        commit(repo, "feature 2", {"feature.py": "2\n", "more.py": "m\n"})
        git(repo, "switch", "-q", "main")
        commit(repo, "main work", {"a.py": "main\n"})
        git(repo, "merge", "-q", "--no-ff", "-m", "merge feature", "feature")
        history = GitRepoReader(repo).first_parent_history()
        assert len(history) == 3  # base, main work, the merge: not the two feature commits
        assert set(history[-1].changed_paths) == {
            "feature.py",
            "more.py",
        }  # the merge, vs. first parent

    def test_another_branch_can_be_tracked(self, repo: Path) -> None:
        commit(repo, "base", {"a.py": "1\n"})
        git(repo, "switch", "-q", "-c", "release")
        commit(repo, "only on release", {"r.py": "1\n"})
        git(repo, "switch", "-q", "main")
        assert len(GitRepoReader(repo, branch="main").first_parent_history()) == 1
        assert len(GitRepoReader(repo, branch="release").first_parent_history()) == 2


class TestWindow:
    def test_the_first_commit_in_a_window_carries_the_whole_tree(self, repo: Path) -> None:
        commit(repo, "old", {"old.py": "1\n", "keep.py": "k\n"}, when="2024-01-01T00:00:00+0000")
        commit(repo, "new", {"new.py": "1\n"}, when="2024-06-01T00:00:00+0000")
        commit(repo, "newer", {"newer.py": "1\n"}, when="2024-07-01T00:00:00+0000")

        history = GitRepoReader(repo).first_parent_history(since=datetime(2024, 5, 1, tzinfo=UTC))

        assert [set(c.changed_paths) for c in history] == [
            {"old.py", "keep.py", "new.py"},  # a snapshot: the KB has never seen old.py
            {"newer.py"},
        ]

    def test_a_window_after_everything_is_empty(self, repo: Path) -> None:
        commit(repo, "old", {"a.py": "1\n"}, when="2024-01-01T00:00:00+0000")
        assert (
            GitRepoReader(repo).first_parent_history(since=datetime(2030, 1, 1, tzinfo=UTC)) == []
        )


class TestFailureAndIsolation:
    def test_a_directory_that_is_not_a_repository_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(GitError):
            GitRepoReader(tmp_path).first_parent_history()

    def test_an_unknown_branch_is_an_error(self, repo: Path) -> None:
        commit(repo, "a", {"a.py": "1\n"})
        with pytest.raises(GitError):
            GitRepoReader(repo, branch="nope").first_parent_history()

    def test_repository_config_cannot_run_anything(
        self, repo: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """A hostile repo may set a filesystem monitor or hooks path; they must not run."""
        marker = tmp_path_factory.mktemp("marker") / "ran"
        commit(repo, "a", {"a.py": "1\n"})
        git(repo, "config", "core.fsmonitor", f"touch {marker}")
        git(repo, "config", "core.hooksPath", str(marker.parent))
        reader = GitRepoReader(repo)
        reader.first_parent_history()
        reader.read_file_at("a.py", git(repo, "rev-parse", "HEAD"))
        assert not marker.exists()


class TestRepoSlug:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://github.com/ontolith/ontolith.git", "ontolith/ontolith"),
            ("git@github.com:mattbv/plumbline.git", "mattbv/plumbline"),
            ("ssh://git@host/team/proj", "team/proj"),
        ],
    )
    def test_it_comes_from_the_origin_remote(self, repo: Path, url: str, expected: str) -> None:
        git(repo, "remote", "add", "origin", url)
        assert repo_slug(repo) == expected

    def test_without_a_remote_it_falls_back_to_the_directory_name(self, repo: Path) -> None:
        assert repo_slug(repo) == f"local/{repo.name}"
