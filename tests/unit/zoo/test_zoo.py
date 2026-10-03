"""The drift zoo's labels are consistent, and its Git repository is reproducible.

Two independent guarantees (PRD §10 M0 exit criterion, first half):
  * every seeded label agrees with an independent statement of the PRD's rules
    (so a mislabeled scenario can't silently corrupt M1's precision/recall);
  * building the zoo twice yields byte-identical repositories.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from tests.zoo import builder, oracle
from tests.zoo.model import Commit, DriftClass, Expectation, Layer, Outcome, Scenario
from tests.zoo.scenarios import ALL

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _ids(scenarios: tuple[Scenario, ...]) -> list[str]:
    return [s.id for s in scenarios]


class TestZooLabels:
    @pytest.mark.parametrize("scenario", ALL, ids=_ids(ALL))
    def test_scenario_is_well_formed_and_labels_match_the_rules(self, scenario: Scenario) -> None:
        assert oracle.lint(scenario) == []

    def test_scenario_ids_are_unique(self) -> None:
        assert len({s.id for s in ALL}) == len(ALL)

    def test_every_routing_outcome_is_exercised(self) -> None:
        seen = {e.outcome for s in ALL for e in s.expectations}
        assert seen == set(Outcome)

    def test_every_drift_class_is_exercised(self) -> None:
        seen = {e.drift_class for s in ALL for e in s.expectations if e.drift_class}
        assert seen >= {DriftClass.DOC_VS_CODE, DriftClass.DOC_VS_DOC_VS_CODE}

    def test_prd_worked_examples_are_covered(self) -> None:
        """PRD §14 #1-#8, #10, #11 are expressible as Git history; #9 (an agent's
        hallucinated fix) needs the shadow-KB flow and belongs to M2."""
        refs = {ref for s in ALL for ref in s.prd_refs}
        expected = {f"§14#{n}" for n in (1, 2, 3, 4, 5, 6, 7, 8, 10, 11)}
        assert expected <= refs


def _scenario(**overrides: object) -> Scenario:
    base = Scenario(
        id="demo",
        title="demo",
        prd_refs=(),
        commits=(
            Commit(
                "c1",
                "init",
                {
                    "src/demo/__init__.py": '"""demo."""\n',
                    "src/demo/m.py": "def f(x=1):\n    pass\n",
                },
            ),
        ),
        expectations=(
            Expectation(
                "c1",
                "py:demo.m.f",
                "param.x.default",
                Layer.L2,
                Outcome.CORROBORATE,
                code_value="1",
                claims=(("plumb-readme", "1"),),
            ),
        ),
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def _with(**changes: object) -> Scenario:
    return _scenario(expectations=(replace(_scenario().expectations[0], **changes),))  # type: ignore[arg-type]


class TestLintCatchesMistakes:
    def test_baseline_is_clean(self) -> None:
        assert oracle.lint(_scenario()) == []

    def test_wrong_outcome_label(self) -> None:
        problems = oracle.lint(
            _with(outcome=Outcome.CONTRADICT, drift_class=DriftClass.DOC_VS_CODE)
        )
        assert any("inputs imply corroborate" in p for p in problems)

    def test_contradiction_requires_the_right_drift_class(self) -> None:
        problems = oracle.lint(
            _with(
                outcome=Outcome.CONTRADICT,
                code_value="2",
                drift_class=DriftClass.DOC_VS_DOC,
            )
        )
        assert any("members imply doc_vs_code" in p for p in problems)

    def test_withheld_value_belongs_on_an_abstention_only(self) -> None:
        problems = oracle.lint(_with(withheld_value="1"))
        assert any("withheld_value belongs on an ABSTAIN" in p for p in problems)

    def test_a_withheld_abstention_is_clean(self) -> None:
        clean = _with(outcome=Outcome.ABSTAIN, code_value=None, withheld_value="1")
        assert oracle.lint(clean) == []

    def test_unknown_aspect(self) -> None:
        assert any("not in the catalog" in p for p in oracle.lint(_with(aspect="param.x.colour")))

    def test_non_canonical_value(self) -> None:
        problems = oracle.lint(_with(code_value='"a"', claims=(("plumb-readme", '"a"'),)))
        assert any("not a canonical literal" in p for p in problems)

    def test_claim_principal_must_be_a_doc_importer(self) -> None:
        problems = oracle.lint(_with(claims=(("plumb-projector", "1"),)))
        assert any("not a doc-claim importer principal" in p for p in problems)

    def test_corroboration_only_aspect_can_never_contradict(self) -> None:
        problems = oracle.lint(
            _with(
                aspect="raises.ValueError",
                outcome=Outcome.CONTRADICT,
                code_value="true",
                claims=(("plumb-docstring", "false"),),
                drift_class=DriftClass.DOC_VS_CODE,
            )
        )
        assert any("corroboration-only" in p for p in problems)

    def test_unknown_commit(self) -> None:
        assert any("unknown commit" in p for p in oracle.lint(_with(commit="nope")))

    def test_symbol_must_belong_to_the_scenario(self) -> None:
        assert any("scenario id" in p for p in oracle.lint(_with(symbol="py:other.m.f")))

    def test_symbol_needs_its_module_to_exist_at_that_commit(self) -> None:
        later = _scenario(
            commits=(
                Commit("c1", "init", {"src/demo/__init__.py": '"""demo."""\n'}),
                Commit("c2", "add m", {"src/demo/m.py": "def f(x=1):\n    pass\n"}),
            ),
            expectations=(_scenario().expectations[0],),
        )
        assert any("no module" in p for p in oracle.lint(later))
        assert (
            oracle.lint(replace(later, expectations=(replace(later.expectations[0], commit="c2"),)))
            == []
        )

    def test_l1_expectation_must_change_value(self) -> None:
        problems = oracle.lint(
            _with(
                layer=Layer.L1,
                outcome=Outcome.SUPERSEDE,
                code_value="1",
                previous_code_value="1",
                claims=(),
            )
        )
        assert any("needs the value to change" in p for p in problems)

    def test_python_files_must_parse(self) -> None:
        bad = _scenario(commits=(Commit("c1", "init", {"src/demo/__init__.py": "def (:\n"}),))
        assert any("does not parse" in p for p in oracle.lint(bad))

    def test_introduced_in_cannot_be_in_the_future(self) -> None:
        two = _scenario(
            commits=(*_scenario().commits, Commit("c2", "more", {"README.md": "x\n"})),
        )
        late = replace(
            two.expectations[0],
            outcome=Outcome.CONTRADICT,
            code_value="2",
            drift_class=DriftClass.DOC_VS_CODE,
            introduced_in="c2",
        )
        problems = oracle.lint(replace(two, expectations=(late,)))
        assert any("after the commit it is observed at" in p for p in problems)

    def test_paths_must_stay_inside_the_scenario(self) -> None:
        bad = _scenario(commits=(Commit("c1", "init", {"../escape.txt": "x"}),))
        assert any("bad path" in p for p in oracle.lint(bad))


class TestResolveAspect:
    @pytest.mark.parametrize(
        ("concrete", "template"),
        [
            ("exists", "exists"),
            ("param.timeout.default", "param.<p>.default"),
            ("param.timeout.exists", "param.<p>.exists"),
            ("raises.json.JSONDecodeError", "raises.<Exc>"),
            ("cli.serve.flag.port.exists", "cli.<cmd>.flag.<f>.exists"),
            ("env.HOME.exists", "env.<VAR>.exists"),
            ("project.requires_python", "project.requires_python"),
        ],
    )
    def test_concrete_names_match_their_template(self, concrete: str, template: str) -> None:
        resolved = oracle.resolve_aspect(concrete)
        assert resolved is not None and resolved.name == template

    @pytest.mark.parametrize("concrete", ["", "param.default", "bogus", "param..default"])
    def test_non_catalog_names_do_not_resolve(self, concrete: str) -> None:
        assert oracle.resolve_aspect(concrete) is None


@needs_git
class TestZooBuildIsReproducible:
    def test_two_builds_are_byte_identical(self, tmp_path: Path) -> None:
        first = builder.build(ALL, tmp_path / "one")
        second = builder.build(ALL, tmp_path / "two")
        assert first.shas == second.shas
        assert first.head_tree() == second.head_tree()

    def test_ambient_git_environment_does_not_leak_into_shas(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clean = builder.build(ALL, tmp_path / "clean")
        monkeypatch.setenv("GIT_AUTHOR_NAME", "Someone Else")
        monkeypatch.setenv("GIT_COMMITTER_DATE", "2001-01-01T00:00:00+0000")
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
        noisy = builder.build(ALL, tmp_path / "noisy")
        assert clean.shas == noisy.shas

    def test_scenario_order_in_the_input_does_not_matter(self, tmp_path: Path) -> None:
        forward = builder.build(ALL, tmp_path / "fwd")
        backward = builder.build(tuple(reversed(ALL)), tmp_path / "rev")
        assert forward.shas == backward.shas

    def test_one_commit_per_scenario_commit_with_monotonic_times(self, tmp_path: Path) -> None:
        built = builder.build(ALL, tmp_path / "zoo")
        total = sum(len(s.commits) for s in ALL)
        assert len(built.shas) == total
        assert len(set(built.shas.values())) == total
        count = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=built.root,
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull},
        ).stdout.strip()
        assert int(count) == total
        times = list(built.committed_at.values())
        assert times == sorted(times) and len(set(times)) == len(times)

    def test_release_tags_point_at_their_commits(self, tmp_path: Path) -> None:
        built = builder.build(ALL, tmp_path / "zoo")
        tag = builder.tag_name("changelog_wrong_removed_in", "2.1.0")
        resolved = subprocess.run(
            ["git", "rev-parse", f"{tag}^{{commit}}"],
            cwd=built.root,
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull},
        ).stdout.strip()
        assert resolved == built.shas[("changelog_wrong_removed_in", "c2")]

    def test_files_land_under_their_scenario_directory(self, tmp_path: Path) -> None:
        built = builder.build(ALL, tmp_path / "zoo")
        readme = built.root / "scenarios" / "sig_change_docs_stale" / "README.md"
        assert "`30`" in readme.read_text(encoding="utf-8")

    def test_deletions_are_applied(self, tmp_path: Path) -> None:
        scenario = _scenario(
            commits=(
                Commit("c1", "add", {"src/demo/__init__.py": "", "gone.txt": "x\n"}),
                Commit("c2", "remove", delete=("gone.txt",)),
            ),
            expectations=(replace(_scenario().expectations[0], commit="c1"),),
        )
        built = builder.build((scenario,), tmp_path / "zoo")
        assert not (built.root / "scenarios" / "demo" / "gone.txt").exists()

    def test_duplicate_ids_are_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="unique"):
            builder.build((_scenario(), _scenario()), tmp_path / "zoo")
