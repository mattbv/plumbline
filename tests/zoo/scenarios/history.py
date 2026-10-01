"""Scenarios that depend on history: renames, removals, deprecation, release lineage."""

from __future__ import annotations

from plumbline.domain.dispositions import Disposition

from ..model import Commit, DriftClass, Expectation, Layer, Outcome, Scenario
from ._util import package, sym, text

_ID1 = "rename_symbol"
RENAME_SYMBOL = Scenario(
    id=_ID1,
    title="old_fn is renamed to new_fn; the README still calls old_fn()",
    prd_refs=("§14#5", "DRF-6"),
    commits=(
        Commit(
            "c1",
            "Add old_fn",
            {
                **package(_ID1),
                f"src/{_ID1}/api.py": "def old_fn():\n    return 1\n",
                "README.md": text("""
                    ```python
                    old_fn()
                    ```
                """),
            },
        ),
        Commit(
            "c2", "Rename old_fn to new_fn", {f"src/{_ID1}/api.py": "def new_fn():\n    return 1\n"}
        ),
    ),
    expectations=(
        Expectation(
            "c1",
            sym(_ID1, "api.old_fn"),
            "exists",
            Layer.L2,
            Outcome.CORROBORATE,
            code_value="true",
            claims=(("plumb-readme", "true"),),
        ),
        Expectation(
            "c2",
            sym(_ID1, "api.old_fn"),
            "exists",
            Layer.L1,
            Outcome.SUPERSEDE,
            code_value="false",
            previous_code_value="true",
        ),
        Expectation(
            "c2",
            sym(_ID1, "api.old_fn"),
            "exists",
            Layer.L2,
            Outcome.CONTRADICT,
            code_value="false",
            claims=(("plumb-readme", "true"),),
            drift_class=DriftClass.DOC_VS_CODE,
            disposition=Disposition.DOCS_STALE,
            note="The fix should carry a 'likely renamed to new_fn' hint (DRF-6, P1).",
        ),
        Expectation(
            "c2",
            sym(_ID1, "api.new_fn"),
            "exists",
            Layer.L2,
            Outcome.UNDOCUMENTED,
            note="The new name is not documented anywhere yet; coverage, not drift (DRF-5).",
        ),
    ),
)

_ID2 = "removed_symbol_still_in_readme"
_TWO_FUNCTIONS = "def helper():\n    return 1\n\n\ndef keep():\n    return 2\n"
REMOVED_SYMBOL_STILL_IN_README = Scenario(
    id=_ID2,
    title="A helper is deleted but the README still tells users to call it",
    prd_refs=("§7.4",),
    commits=(
        Commit(
            "c1",
            "Add helper and keep",
            {
                **package(_ID2),
                f"src/{_ID2}/util.py": _TWO_FUNCTIONS,
                "README.md": "Call `helper()` before `keep()`.\n",
            },
        ),
        Commit("c2", "Remove helper", {f"src/{_ID2}/util.py": "def keep():\n    return 2\n"}),
    ),
    expectations=(
        Expectation(
            "c2",
            sym(_ID2, "util.helper"),
            "exists",
            Layer.L1,
            Outcome.SUPERSEDE,
            code_value="false",
            previous_code_value="true",
        ),
        Expectation(
            "c2",
            sym(_ID2, "util.helper"),
            "exists",
            Layer.L2,
            Outcome.CONTRADICT,
            code_value="false",
            claims=(("plumb-readme", "true"),),
            drift_class=DriftClass.DOC_VS_CODE,
            disposition=Disposition.DOCS_STALE,
        ),
        Expectation(
            "c2",
            sym(_ID2, "util.keep"),
            "exists",
            Layer.L2,
            Outcome.CORROBORATE,
            code_value="true",
            claims=(("plumb-readme", "true"),),
        ),
    ),
)

_ID3 = "changelog_wrong_removed_in"
CHANGELOG_WRONG_REMOVED_IN = Scenario(
    id=_ID3,
    title="CHANGELOG says foo was removed in 2.1.0; history shows it present at 2.1.0",
    prd_refs=("§14#7", "ING-9"),
    commits=(
        Commit(
            "c1",
            "Release 2.0.0 with foo",
            {**package(_ID3), f"src/{_ID3}/api.py": "def foo():\n    return 1\n"},
            tag="2.0.0",
        ),
        Commit("c2", "Release 2.1.0", {"VERSION": "2.1.0\n"}, tag="2.1.0"),
        Commit(
            "c3",
            "Remove foo and release 2.2.0",
            {
                f"src/{_ID3}/api.py": "def bar():\n    return 1\n",
                "CHANGELOG.md": text("""
                    # Changelog

                    ## [2.1.0]
                    ### Removed
                    - `foo`
                """),
            },
            tag="2.2.0",
        ),
    ),
    expectations=(
        Expectation(
            "c3",
            sym(_ID3, "api.foo"),
            "exists",
            Layer.L1,
            Outcome.SUPERSEDE,
            code_value="false",
            previous_code_value="true",
        ),
        Expectation(
            "c3",
            sym(_ID3, "api.foo"),
            "exists",
            Layer.L2,
            Outcome.CORROBORATE,
            code_value="false",
            claims=(("plumb-changelog", "false"),),
            note="The changelog is right that foo is gone, just wrong about when.",
        ),
        Expectation(
            "c3",
            sym(_ID3, "api.foo"),
            "removed_in",
            Layer.L2,
            Outcome.CONTRADICT,
            code_value="2.2.0",
            claims=(("plumb-changelog", "2.1.0"),),
            drift_class=DriftClass.DOC_VS_CODE,
            disposition=Disposition.DOCS_STALE,
            note="foo is present at the 2.1.0 tag and gone at 2.2.0 -- a historical fact (§14#7).",
        ),
    ),
)

_ID4 = "changelog_wrong_added_in"
CHANGELOG_WRONG_ADDED_IN = Scenario(
    id=_ID4,
    title="CHANGELOG credits foo to 1.0.0 but it first shipped in 1.1.0",
    prd_refs=("§7.4", "ING-9"),
    commits=(
        Commit(
            "c1",
            "Release 1.0.0",
            {**package(_ID4), f"src/{_ID4}/api.py": "def other():\n    return 0\n"},
            tag="1.0.0",
        ),
        Commit(
            "c2",
            "Add foo and release 1.1.0",
            {
                f"src/{_ID4}/api.py": "def other():\n    return 0\n\n\ndef foo():\n    return 1\n",
                "CHANGELOG.md": text("""
                    # Changelog

                    ## [1.0.0]
                    ### Added
                    - `foo`
                """),
            },
            tag="1.1.0",
        ),
    ),
    expectations=(
        Expectation(
            "c2",
            sym(_ID4, "api.foo"),
            "exists",
            Layer.L2,
            Outcome.CORROBORATE,
            code_value="true",
            claims=(("plumb-changelog", "true"),),
        ),
        Expectation(
            "c2",
            sym(_ID4, "api.foo"),
            "added_in",
            Layer.L2,
            Outcome.CONTRADICT,
            code_value="1.1.0",
            claims=(("plumb-changelog", "1.0.0"),),
            drift_class=DriftClass.DOC_VS_CODE,
            disposition=Disposition.DOCS_STALE,
        ),
    ),
)

_ID5 = "deprecation_docs_ahead"
DEPRECATION_DOCS_AHEAD = Scenario(
    id=_ID5,
    title="The docstring says deprecated but the code carries no deprecation marker",
    prd_refs=("§7.4",),
    commits=(
        Commit(
            "c1",
            "Document old() as deprecated without marking it",
            {
                **package(_ID5),
                f"src/{_ID5}/api.py": text('''
                    def old():
                        """Do the old thing.

                        .. deprecated:: 1.2
                           Use ``new`` instead.
                        """
                        return 1
                '''),
            },
        ),
    ),
    expectations=(
        Expectation(
            "c1",
            sym(_ID5, "api.old"),
            "deprecated",
            Layer.L2,
            Outcome.CONTRADICT,
            code_value="false",
            claims=(("plumb-docstring", "true"),),
            drift_class=DriftClass.DOC_VS_CODE,
            note="No marker projects 'false'; a human decides whether the code or docs lag.",
        ),
    ),
)

_ID6 = "deprecation_in_sync"
DEPRECATION_IN_SYNC = Scenario(
    id=_ID6,
    title="The code and the docstring both mark old() deprecated",
    prd_refs=("§7.4",),
    commits=(
        Commit(
            "c1",
            "Deprecate old() in code and docs",
            {
                **package(_ID6),
                f"src/{_ID6}/api.py": text('''
                    from typing_extensions import deprecated


                    @deprecated("Use new() instead")
                    def old():
                        """Do the old thing.

                        .. deprecated:: 1.2
                           Use ``new`` instead.
                        """
                        return 1
                '''),
            },
        ),
    ),
    expectations=(
        Expectation(
            "c1",
            sym(_ID6, "api.old"),
            "deprecated",
            Layer.L2,
            Outcome.CORROBORATE,
            code_value="true",
            claims=(("plumb-docstring", "true"),),
        ),
    ),
)

_ID7 = "deprecation_code_ahead"
DEPRECATION_CODE_AHEAD = Scenario(
    id=_ID7,
    title="Code adds @deprecated; the docs say nothing about deprecation",
    prd_refs=("DRF-5",),
    commits=(
        Commit(
            "c1",
            "Add old() and mention it in the README",
            {
                **package(_ID7),
                f"src/{_ID7}/api.py": "def old():\n    return 1\n",
                "README.md": "Call `old()` for the legacy behavior.\n",
            },
        ),
        Commit(
            "c2",
            "Deprecate old() in code only",
            {
                f"src/{_ID7}/api.py": text("""
                    from typing_extensions import deprecated


                    @deprecated("Use new() instead")
                    def old():
                        return 1
                """)
            },
        ),
    ),
    expectations=(
        Expectation(
            "c2",
            sym(_ID7, "api.old"),
            "deprecated",
            Layer.L1,
            Outcome.SUPERSEDE,
            code_value="true",
            previous_code_value="false",
        ),
        Expectation(
            "c2",
            sym(_ID7, "api.old"),
            "deprecated",
            Layer.L2,
            Outcome.UNDOCUMENTED,
            code_value="true",
            note="A projection with no claim to meet is a coverage gap, never drift (DRF-5).",
        ),
    ),
)

SCENARIOS: tuple[Scenario, ...] = (
    RENAME_SYMBOL,
    REMOVED_SYMBOL_STILL_IN_README,
    CHANGELOG_WRONG_REMOVED_IN,
    CHANGELOG_WRONG_ADDED_IN,
    DEPRECATION_DOCS_AHEAD,
    DEPRECATION_IN_SYNC,
    DEPRECATION_CODE_AHEAD,
)
