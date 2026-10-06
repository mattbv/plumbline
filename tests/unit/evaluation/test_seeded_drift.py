"""The seeded-drift harness must report what happened, including its own failures."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from evaluation import seeded_drift as sd

from plumbline.adapters.ontolith_kb import OntolithKnowledgeBase
from plumbline.application.drift import DriftClaim, DriftClass, DriftItem
from plumbline.application.projection import PROJECTOR_PRINCIPAL

WHEN = datetime(2024, 1, 1, tzinfo=UTC)
FACT = "py:m.f#param.x.default"


def item(code: str, docs: str, fact: str = FACT) -> DriftItem:
    return DriftItem(
        fact,
        DriftClass.DOC_VS_CODE,
        WHEN,
        (
            DriftClaim(PROJECTOR_PRINCIPAL, code, "m.py", "u", 1.0),
            DriftClaim("plumb-docstring", docs, "m.py", "u", 0.9),
        ),
    )


def injection(category: str = "code_default", **kw: str | None) -> sd.Injection:
    return sd.Injection(
        category, "m.py", "f", "desc", lambda s: s, **{"expect_fact": FACT, "expect_code": "8",
        "expect_docs": "1", **kw},
    )  # fmt: skip


class TestJudge:
    def test_the_expected_finding_with_the_expected_values_is_found(self) -> None:
        assert sd.judge(injection(), [item("8", "1")]).verdict == "found"

    def test_no_finding_is_a_miss(self) -> None:
        out = sd.judge(injection(), [])
        assert out.verdict == "missed" and out.expected_fact == FACT

    def test_a_finding_on_the_wrong_fact_is_a_miss_and_is_listed_as_extra(self) -> None:
        out = sd.judge(injection(), [item("8", "1", fact="py:m.f#param.y.default")])
        assert out.verdict == "missed" and out.extra_findings == ["py:m.f#param.y.default"]

    def test_an_unprovable_type_difference_is_abstained_not_missed(self) -> None:
        inj = injection(expect_fact="py:m.f#param.x.type", expect_code="str", expect_docs="Style")
        assert sd.judge(inj, []).verdict == "abstained"

    def test_a_provable_type_difference_that_was_not_found_is_still_a_miss(self) -> None:
        inj = injection(expect_fact="py:m.f#param.x.type", expect_code="str", expect_docs="int")
        assert sd.judge(inj, []).verdict == "missed"

    def test_a_concrete_default_is_never_abstained(self) -> None:
        inj = injection(expect_fact="py:m.f#param.x.default", expect_code="1", expect_docs="2")
        assert sd.judge(inj, []).verdict == "missed"

    def test_a_docs_default_changed_behind_a_none_code_default_is_abstained(self) -> None:
        """A None default is a sentinel (ADR-0007 Amendment 5 D): withheld on purpose."""
        inj = injection(expect_fact="py:m.f#param.x.default", expect_code="None", expect_docs="0")
        assert sd.judge(inj, []).verdict == "abstained"

    def test_a_code_default_changed_away_from_none_is_a_real_miss_if_not_found(self) -> None:
        inj = injection(expect_fact="py:m.f#param.x.default", expect_code="0", expect_docs="None")
        assert sd.judge(inj, []).verdict == "missed"

    def test_the_right_fact_with_the_wrong_values_is_not_counted_as_found(self) -> None:
        assert sd.judge(injection(), [item("9", "1")]).verdict == "found_wrong_values"
        assert sd.judge(injection(), [item("8", "2")]).verdict == "found_wrong_values"

    def test_an_alternative_doc_value_that_is_also_right_counts(self) -> None:
        inj = injection(expect_docs="str", alt_docs=("None | str",))
        assert sd.judge(inj, [item("8", "None | str")]).verdict == "found"

    def test_a_value_that_is_neither_is_not_found(self) -> None:
        inj = injection(expect_docs="str", alt_docs=("None | str",))
        assert sd.judge(inj, [item("8", "bytes")]).verdict == "found_wrong_values"

    def test_extra_findings_beside_the_expected_one_are_recorded(self) -> None:
        out = sd.judge(injection(), [item("8", "1"), item("1", "2", fact="py:m.f#other")])
        assert out.verdict == "found" and out.extra_findings == ["py:m.f#other"]

    def test_a_control_with_no_finding_is_clean(self) -> None:
        assert sd.judge(injection("comment_added"), []).verdict == "clean"

    def test_a_control_with_a_finding_is_a_false_positive(self) -> None:
        out = sd.judge(injection("comment_added"), [item("8", "1")])
        assert out.verdict == "false_positive" and out.extra_findings == [FACT]

    def test_the_by_design_blind_spot_is_silent_not_missed(self) -> None:
        assert sd.judge(injection("raise_removed"), []).verdict == "silent"
        assert sd.judge(injection("raise_removed"), [item("8", "1")]).verdict == "surprising"


class TestReport:
    def report(self, *outcomes: sd.Outcome, requested: dict[str, int] | None = None) -> sd.Report:
        return sd.Report("r", 1, 1, 0, {}, {}, requested or {}, list(outcomes))

    def outcome(self, category: str, verdict: str) -> sd.Outcome:
        kind = sd.Injection(category, "p", "q", "d", lambda s: s).kind
        return sd.Outcome(category, kind, "d", "p", verdict, None)

    def test_recall_counts_only_exact_hits_over_injections(self) -> None:
        r = self.report(
            self.outcome("code_default", "found"),
            self.outcome("docs_default", "missed"),
            self.outcome("code_return_type", "found_wrong_values"),
            self.outcome("comment_added", "clean"),
        )
        assert r.recall() == (1, 3)

    def test_abstentions_are_in_neither_side_of_recall(self) -> None:
        r = self.report(
            self.outcome("code_default", "found"),
            self.outcome("code_param_type", "abstained"),
            self.outcome("code_return_type", "abstained"),
        )
        assert r.recall() == (1, 1) and r.abstained() == 2

    def test_false_positives_count_only_controls(self) -> None:
        r = self.report(
            self.outcome("comment_added", "false_positive"),
            self.outcome("statement_added", "clean"),
            self.outcome("code_default", "found"),
        )
        assert r.false_positives() == (1, 2)

    def test_a_shortfall_names_the_category_and_the_counts(self) -> None:
        r = self.report(
            self.outcome("code_default", "found"),
            requested={"code_default": 3, "docs_default": 2},
        )
        assert r.shortfalls() == {"code_default": (1, 3), "docs_default": (0, 2)}

    def test_no_shortfall_when_everything_ran(self) -> None:
        r = self.report(self.outcome("code_default", "found"), requested={"code_default": 1})
        assert r.shortfalls() == {}

    def test_the_text_report_shows_misses_and_shortfalls(self) -> None:
        r = self.report(self.outcome("code_default", "missed"), requested={"code_default": 2})
        text = sd.format_report(r)
        assert "RECALL on provable drift     0/1 = 0%" in text
        assert "SHORTFALL" in text and "code_default: 1 of 2" in text
        assert "[missed]" in text


def make_repo(root: Path, source: str) -> Path:
    root.mkdir(parents=True)
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@e.invalid",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@e.invalid",
        "GIT_AUTHOR_DATE": "2024-01-01T00:00:00+0000",
        "GIT_COMMITTER_DATE": "2024-01-01T00:00:00+0000",
    }  # fmt: skip
    (root / "src" / "p").mkdir(parents=True)
    (root / "src" / "p" / "__init__.py").write_bytes(b'"""p."""\n')
    (root / "src" / "p" / "m.py").write_bytes(source.encode())
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "i"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, env=env)
    return root


SOURCE = '''def f(a: int = 1, label: str = "x") -> int:
    """Doc.

    Args:
        a (int): A. Defaults to 1.
        label (str): L. Defaults to 'x'.

    Returns:
        int: R.
    """
    return a
'''


class TestRun:
    def test_it_finds_injected_drift_and_leaves_the_source_untouched(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path / "repo", SOURCE)
        head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        report = sd.run(
            repo, tmp_path / "work", per_category=1, categories=("code_default",), seed=1
        )
        assert report.recall() == (1, 1)
        after = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert after == head and (repo / "src/p/m.py").read_bytes() == SOURCE.encode()

    def test_a_run_that_injects_nothing_fails_instead_of_reporting_success(
        self, tmp_path: Path
    ) -> None:
        repo = make_repo(tmp_path / "repo", "def g():\n    return 1\n")
        with pytest.raises(sd.NothingInjected):
            sd.run(repo, tmp_path / "work", per_category=1, categories=("code_default",))

    def test_a_shortfall_is_reported_when_there_is_too_little_code(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path / "repo", SOURCE)
        report = sd.run(
            repo, tmp_path / "work", per_category=3, categories=("code_default",), seed=1
        )
        assert report.shortfalls() == {"code_default": (1, 3)}

    def test_the_same_seed_picks_the_same_injections(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path / "repo", SOURCE)
        runs = [
            sd.run(repo, tmp_path / f"w{i}", per_category=2, categories=("code_default",), seed=5)
            for i in range(2)
        ]
        assert [o.description for o in runs[0].outcomes] == [
            o.description for o in runs[1].outcomes
        ]

    def test_a_tool_that_finds_nothing_is_reported_as_missing_every_injection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The harness must be able to say "missed": make the tool report nothing at all."""
        repo = make_repo(tmp_path / "repo", SOURCE)
        monkeypatch.setattr(OntolithKnowledgeBase, "open_drift", lambda self: [])
        report = sd.run(repo, tmp_path / "work", per_category=1, categories=("code_default",))
        assert report.recall() == (0, 1)
        assert [o.verdict for o in report.outcomes] == ["missed"]


def candidate(aspect: str = "param.a.exists", value: str = "true") -> sd.Candidate:
    return sd.Candidate(f"py:p.m.f#{aspect}", "py:p.m.f", aspect, "src/p/m.py", "f", value)


class TestWhichEditsApply:
    DOC = '    """Doc.\n\n    Args:\n        a (int): A. Defaults to 1.\n    """\n'
    PLAIN = f'def f(a: int = 1, b: str = "x"):\n{DOC}    return a\n'
    KWARGS = f"def f(a: int = 1, **kwargs):\n{DOC}    return a\n"
    STAR_ARGS = f"def f(a: int = 1, *args):\n{DOC}    return a\n"

    @pytest.mark.parametrize("category", ["code_param_renamed", "docs_param_invented"])
    def test_a_missing_parameter_is_injected_when_nothing_could_absorb_it(
        self, category: str
    ) -> None:
        built = sd.build(category, candidate(), set(), 1)
        assert built is not None and built.edit(self.PLAIN) is not None

    @pytest.mark.parametrize("category", ["code_param_renamed", "docs_param_invented"])
    def test_a_missing_parameter_is_not_injected_where_kwargs_could_absorb_it(
        self, category: str
    ) -> None:
        # With **kwargs the tool cannot prove a parameter absent, so staying silent is correct;
        # injecting here would count a by-design abstention as a miss.
        built = sd.build(category, candidate(), set(), 1)
        assert built is not None and built.edit(self.KWARGS) is None
        assert built.edit(self.STAR_ARGS) is None

    def test_an_undocumented_control_skips_every_fact_the_docstring_states(self) -> None:
        both = {"py:p.m.f#param.a.default", "py:p.m.f#param.b.default"}
        control = sd.build("undocumented_default_changed", candidate(), both, 1)
        assert control is not None and control.edit(self.PLAIN) is None

    def test_an_undocumented_control_changes_the_one_fact_the_docstring_is_silent_on(self) -> None:
        stated = {"py:p.m.f#param.a.default"}
        control = sd.build("undocumented_default_changed", candidate(), stated, 1)
        assert control is not None
        out = control.edit(self.PLAIN)
        assert out is not None and "a: int = 1" in out and 'b: str = "x"' not in out

    def test_an_undocumented_type_control_leaves_documented_types_alone(self) -> None:
        stated = {"py:p.m.f#param.a.type"}
        control = sd.build("undocumented_type_changed", candidate(), stated, 1)
        assert control is not None
        out = control.edit(self.PLAIN)
        assert out is not None and "a: int" in out and "b: int" in out


class TestOtherType:
    @pytest.mark.parametrize(
        ("original", "replacement"),
        [
            ("int", "str"),
            ("str", "int"),
            ("None | str", "int"),
            ("int | str", "bytes"),
            ("list[str]", "str"),
            ("Style", "str"),
        ],
    )
    def test_the_replacement_is_never_one_of_the_original_members(
        self, original: str, replacement: str
    ) -> None:
        assert sd._other_type(original) == replacement


class TestDeprecationInjectionGuard:
    DOC = '    """Doc.\n\n    Args:\n        a (int): A.\n    """\n'

    def source(self, decorator: str = "") -> str:
        return f"{decorator}def f(a: int = 1):\n{self.DOC}    return a\n"

    def test_a_plain_function_can_be_given_a_false_deprecation_claim(self) -> None:
        built = sd.build("docs_deprecated", candidate(), set(), 1)
        assert built is not None and built.edit(self.source()) is not None

    def test_a_function_with_an_unknown_decorator_is_skipped(self) -> None:
        """The importer says nothing there, so the injection would be an unfair miss."""
        built = sd.build("docs_deprecated", candidate(), set(), 1)
        assert built is not None and built.edit(self.source("@mystery\n")) is None

    def test_a_function_that_is_already_deprecated_is_skipped(self) -> None:
        built = sd.build("docs_deprecated", candidate(), set(), 1)
        assert built is not None and built.edit(self.source("@deprecated('x')\n")) is None
