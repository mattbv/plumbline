"""`plumb ingest` and `plumb drift` end to end, over a real Git repository."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from plumbline.adapters.git_reader import GitRepoReader
from plumbline.adapters.ontolith_kb import OntolithKnowledgeBase
from plumbline.interfaces.cli import app
from tests.zoo import builder
from tests.zoo.scenarios import ALL

pytestmark = pytest.mark.integration

runner = CliRunner()
TOTAL_COMMITS = sum(len(s.commits) for s in ALL)


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return builder.build(ALL, tmp_path_factory.mktemp("cli-repo")).root


def ingest(repo: Path, kb: Path, *extra: str):  # type: ignore[no-untyped-def]
    return runner.invoke(app, ["ingest", "--repo", str(repo), "--kb", str(kb), *extra])


class TestIngest:
    def test_it_replays_the_whole_history_and_says_what_it_did(
        self, repo: Path, tmp_path: Path
    ) -> None:
        result = ingest(repo, tmp_path / "kb.db")

        assert result.exit_code == 0, result.output
        assert f"Ingested {TOTAL_COMMITS} commit(s)." in result.output
        for line in (
            "code facts written",
            "projections stated",
            "abstentions",
            "ownership conflicts",
        ):
            assert line in result.output
        kb = OntolithKnowledgeBase.open(tmp_path / "kb.db")
        assert (kb.symbol_fields("py:sig_change_docs_stale.client.connect") or {})[
            "kind"
        ] == "function"

    def test_it_only_reads_the_repository(self, repo: Path, tmp_path: Path) -> None:
        before = sorted(
            p.relative_to(repo).as_posix() for p in repo.rglob("*") if ".git/" not in p.as_posix()
        )
        ingest(repo, tmp_path / "kb.db")
        after = sorted(
            p.relative_to(repo).as_posix() for p in repo.rglob("*") if ".git/" not in p.as_posix()
        )
        assert before == after

    def test_running_it_again_ingests_nothing_more(self, repo: Path, tmp_path: Path) -> None:
        ingest(repo, tmp_path / "kb.db")
        again = ingest(repo, tmp_path / "kb.db")
        assert again.exit_code == 0 and "Ingested 0 commit(s) (resumed)." in again.output

    def test_it_resumes_after_a_partial_run(self, repo: Path, tmp_path: Path) -> None:
        first = ingest(repo, tmp_path / "kb.db", "--limit", "5")
        assert "Ingested 5 commit(s)." in first.output
        rest = ingest(repo, tmp_path / "kb.db")
        assert f"Ingested {TOTAL_COMMITS - 5} commit(s) (resumed)." in rest.output

    def test_a_resumed_run_ends_in_the_same_state_as_an_uninterrupted_one(
        self, repo: Path, tmp_path: Path
    ) -> None:
        ingest(repo, tmp_path / "whole.db")
        ingest(repo, tmp_path / "split.db", "--limit", "17")
        ingest(repo, tmp_path / "split.db")
        a, b = (OntolithKnowledgeBase.open(tmp_path / n) for n in ("whole.db", "split.db"))
        assert {i.fact_key for i in a.open_drift()} == {i.fact_key for i in b.open_drift()}
        key = "py:docstring_edit.client.connect"
        assert a.symbol_fields(key) == b.symbol_fields(key)

    def test_the_state_file_records_where_it_stopped(self, repo: Path, tmp_path: Path) -> None:
        ingest(repo, tmp_path / "kb.db", "--limit", "3")
        state = json.loads((tmp_path / "kb.db.ingest.json").read_text())
        last = GitRepoReader(repo).first_parent_history()[2].sha
        assert (state["last_sha"], state["commits"]) == (last, 3)

    def test_it_can_write_its_totals_as_json(self, repo: Path, tmp_path: Path) -> None:
        ingest(repo, tmp_path / "kb.db", "--report", str(tmp_path / "totals.json"))
        totals = json.loads((tmp_path / "totals.json").read_text())
        assert totals["commits"] == TOTAL_COMMITS and totals["l1_writes"] > 100

    def test_a_since_window_starts_from_a_snapshot_of_the_whole_tree(
        self, repo: Path, tmp_path: Path
    ) -> None:
        history = GitRepoReader(repo).first_parent_history()
        midpoint = history[len(history) // 2].committed_at
        result = ingest(repo, tmp_path / "kb.db", "--since", midpoint.date().isoformat())
        assert result.exit_code == 0
        assert "Ingested" in result.output and f"Ingested {TOTAL_COMMITS} " not in result.output
        kb = OntolithKnowledgeBase.open(tmp_path / "kb.db")
        # Code that predates the window is known anyway, because the first commit carries the tree.
        assert kb.symbol_fields("py:abstention_placeholder") is None
        assert kb.symbol_fields("py:adr_superseded.client.connect") is not None

    def test_extra_exclusions_are_honoured(self, repo: Path, tmp_path: Path) -> None:
        ingest(repo, tmp_path / "kb.db", "--exclude", "scenarios/adr_*")
        kb = OntolithKnowledgeBase.open(tmp_path / "kb.db")
        assert kb.symbol_fields("py:adr_superseded.client.connect") is None
        assert kb.symbol_fields("py:sig_change_docs_stale.client.connect") is not None


class TestRefusals:
    def test_a_kb_with_data_from_outside_is_refused(self, repo: Path, tmp_path: Path) -> None:
        kb = OntolithKnowledgeBase.initialize(tmp_path / "kb.db", admin_principal_id="a@x.invalid")
        kb.record_code_fact(
            "py:m.f",
            "kind",
            "function",
            as_of=GitRepoReader(repo).first_parent_history()[0].committed_at,
            source="s",
        )
        kb.close()
        result = ingest(repo, tmp_path / "kb.db")
        assert result.exit_code == 1 and "fresh KB" in result.output

    def test_an_empty_kb_from_plumb_init_is_fine(self, repo: Path, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()
        assert (
            runner.invoke(
                app, ["init", "--admin", "me@x.invalid", "--path", str(project)]
            ).exit_code
            == 0
        )
        result = runner.invoke(
            app, ["ingest", "--path", str(project), "--repo", str(repo), "--limit", "3"]
        )
        assert result.exit_code == 0 and "Ingested 3 commit(s)." in result.output

    def test_a_state_file_from_a_different_run_is_refused(self, repo: Path, tmp_path: Path) -> None:
        ingest(repo, tmp_path / "kb.db", "--limit", "2")
        result = ingest(repo, tmp_path / "kb.db", "--since", "2030-01-01")
        assert result.exit_code == 1 and "different run" in result.output

    def test_rewritten_history_is_detected(self, repo: Path, tmp_path: Path) -> None:
        ingest(repo, tmp_path / "kb.db", "--limit", "2")
        state_path = tmp_path / "kb.db.ingest.json"
        state = json.loads(state_path.read_text())
        state["last_sha"] = "f" * 40
        state_path.write_text(json.dumps(state))
        result = ingest(repo, tmp_path / "kb.db")
        assert result.exit_code == 1 and "no longer on the branch" in result.output

    def test_a_directory_that_is_not_a_repository_is_an_error(self, tmp_path: Path) -> None:
        (tmp_path / "plain").mkdir()
        result = ingest(tmp_path / "plain", tmp_path / "kb.db")
        assert result.exit_code == 1 and "git:" in result.output

    def test_with_no_config_and_no_kb_it_explains(self, repo: Path, tmp_path: Path) -> None:
        result = runner.invoke(app, ["ingest", "--path", str(tmp_path), "--repo", str(repo)])
        assert result.exit_code == 1 and "Pass --kb" in result.output


@pytest.fixture(scope="module")
def ingested_kb(repo: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    kb = tmp_path_factory.mktemp("drift") / "kb.db"
    assert ingest(repo, kb).exit_code == 0
    return kb


class TestDrift:
    def test_it_lists_the_contradictions_the_pipeline_found(self, ingested_kb: Path) -> None:
        result = runner.invoke(app, ["drift", "--kb", str(ingested_kb)])
        assert result.exit_code == 0, result.output
        assert "open contradiction(s)" in result.output
        # A docstring edited to 60 while the code still says 30 (the docstring_edit scenario):
        assert "py:docstring_edit.client.connect#param.timeout.default" in result.output
        assert "doc_vs_code" in result.output

    def test_it_shows_both_sides_with_where_each_came_from(self, ingested_kb: Path) -> None:
        out = runner.invoke(app, ["drift", "--kb", str(ingested_kb), "--limit", "50"]).output
        block = out[
            out.index("py:docstring_edit.client.connect#param.timeout.default") :
        ].splitlines()[:3]
        assert any("code" in line and "'30'" in line for line in block)
        assert any("docstring" in line and "'60'" in line and "client.py" in line for line in block)

    def test_it_does_not_report_the_false_positives_found_on_a_real_repository(
        self, ingested_kb: Path
    ) -> None:
        out = runner.invoke(app, ["drift", "--kb", str(ingested_kb), "--limit", "500"]).output
        assert "varargs_documented_by_bare_name" not in out  # a *args parameter documented by name
        assert "wraps_decorator_preserves" not in out  # a signature behind a @wraps wrapper

    def test_limit_caps_the_listing(self, ingested_kb: Path) -> None:
        out = runner.invoke(app, ["drift", "--kb", str(ingested_kb), "--limit", "1"]).output
        assert "more (use --limit)" in out

    def test_with_nothing_found_it_says_so(self, tmp_path: Path) -> None:
        OntolithKnowledgeBase.initialize(
            tmp_path / "kb.db", admin_principal_id="a@x.invalid"
        ).close()
        result = runner.invoke(app, ["drift", "--kb", str(tmp_path / "kb.db")])
        assert result.exit_code == 0 and "No open contradictions." in result.output

    def test_a_missing_kb_is_an_error(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["drift", "--kb", str(tmp_path / "nope.db")])
        assert result.exit_code == 1 and "No knowledge base" in result.output
