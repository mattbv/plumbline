"""Scenarios about symbols leaving, and about when they must *not* be reported as gone (ADR-0005).

Each ``StateExpectation`` is a statement about what the KB stores afterwards.
The rule throughout: every uncertain case leaves the KB as it was, because a
wrong "removed" is a false drift report.
"""

from __future__ import annotations

from ..model import Commit, Expectation, Layer, Outcome, Scenario, StateExpectation
from ._util import package, sym, text


def _src(scenario_id: str, module: str) -> str:
    return f"src/{scenario_id}/{module}.py"


def _state(
    scenario_id: str, commit: str, dotted: str, present: bool, **kwargs: str | None
) -> StateExpectation:
    symbol = f"py:{scenario_id}" if not dotted else sym(scenario_id, dotted)
    return StateExpectation(commit, symbol, present, **kwargs)  # type: ignore[arg-type]


_ID1 = "file_deleted"
FILE_DELETED = Scenario(
    id=_ID1,
    title="Deleting a file removes the module and everything it defined",
    prd_refs=("ADR-0005", "§14#5"),
    commits=(
        Commit(
            "c1",
            "Add api with two functions",
            {**package(_ID1), _src(_ID1, "api"): "def f(): ...\n\n\ndef g(): ...\n"},
        ),
        Commit("c2", "Delete api", delete=(_src(_ID1, "api"),)),
    ),
    expectations=(),
    states=(
        _state(_ID1, "c1", "api", True, kind="module"),
        _state(_ID1, "c1", "api.f", True, kind="function"),
        _state(_ID1, "c1", "api.g", True, kind="function"),
        _state(_ID1, "c2", "api", False),
        _state(_ID1, "c2", "api.f", False),
        _state(_ID1, "c2", "api.g", False),
        _state(_ID1, "c2", "", True, note="The package itself is untouched."),
    ),
)

_ID2 = "class_removed_with_members"
CLASS_REMOVED_WITH_MEMBERS = Scenario(
    id=_ID2,
    title="Removing a class removes its members, but not its sibling function",
    prd_refs=("ADR-0005",),
    commits=(
        Commit(
            "c1",
            "Add a class and a function",
            {
                **package(_ID2),
                _src(_ID2, "api"): text("""
                    class C:
                        def m(self): ...
                        def n(self): ...


                    def keep(): ...
                """),
            },
        ),
        Commit("c2", "Remove the class", {_src(_ID2, "api"): "def keep(): ...\n"}),
    ),
    expectations=(
        Expectation(
            "c2",
            sym(_ID2, "api.C.m"),
            "exists",
            Layer.L1,
            Outcome.SUPERSEDE,
            code_value="false",
            previous_code_value="true",
        ),
    ),
    states=(
        _state(_ID2, "c2", "api.C", False),
        _state(_ID2, "c2", "api.C.m", False),
        _state(_ID2, "c2", "api.C.n", False),
        _state(_ID2, "c2", "api.keep", True),
    ),
)

_ID3 = "file_renamed"
FILE_RENAMED = Scenario(
    id=_ID3,
    title="Renaming a file changes module keys: the old ones go, the new ones appear",
    prd_refs=("ADR-0005", "§14#5", "DRF-6"),
    commits=(
        Commit("c1", "Add old", {**package(_ID3), _src(_ID3, "old"): "def f(): ...\n"}),
        Commit(
            "c2",
            "Rename old to new",
            {_src(_ID3, "new"): "def f(): ...\n"},
            delete=(_src(_ID3, "old"),),
        ),
    ),
    expectations=(),
    states=(
        _state(_ID3, "c2", "old", False),
        _state(_ID3, "c2", "old.f", False),
        _state(_ID3, "c2", "new", True, kind="module", defined_at=_src(_ID3, "new")),
        _state(_ID3, "c2", "new.f", True, kind="function"),
    ),
)

_ID4 = "layout_move_same_key"
_MOVED = f"lib/src/{_ID4}"
LAYOUT_MOVE_SAME_KEY = Scenario(
    id=_ID4,
    title="Moving a package to another source root keeps the key and changes the path",
    prd_refs=("ADR-0005",),
    commits=(
        Commit("c1", "Package under src/", {**package(_ID4), _src(_ID4, "mod"): "def f(): ...\n"}),
        Commit(
            "c2",
            "Move it into lib/src/",
            {
                f"{_MOVED}/__init__.py": f'"""{_ID4}."""\n',
                f"{_MOVED}/mod.py": "def f(): ...\n",
            },
            delete=(f"src/{_ID4}/__init__.py", _src(_ID4, "mod")),
        ),
    ),
    expectations=(),
    states=(
        _state(_ID4, "c1", "mod.f", True, defined_at=_src(_ID4, "mod")),
        _state(
            _ID4,
            "c2",
            "mod.f",
            True,
            defined_at=f"{_MOVED}/mod.py",
            note="Same key, new owner: the old path was deleted, so the key was free.",
        ),
    ),
)

_ID5 = "syntax_error_edit"
SYNTAX_ERROR_EDIT = Scenario(
    id=_ID5,
    title="A half-typed edit must not look like deleting the whole file",
    prd_refs=("ADR-0005", "DRF-3"),
    commits=(
        Commit(
            "c1",
            "Add api",
            {**package(_ID5), _src(_ID5, "api"): "def f(): ...\n\n\ndef g(): ...\n"},
        ),
        Commit(
            "c2",
            "Break the syntax",
            {_src(_ID5, "api"): "def f(:\n"},
            broken=(_src(_ID5, "api"),),
        ),
        Commit("c3", "Fix it, dropping g", {_src(_ID5, "api"): "def f(): ...\n"}),
    ),
    expectations=(),
    states=(
        _state(_ID5, "c2", "api.f", True, note="Left untouched: no analysis, no inference."),
        _state(_ID5, "c2", "api.g", True),
        _state(_ID5, "c3", "api.f", True),
        _state(_ID5, "c3", "api.g", False, note="Removal resumes once the file parses again."),
    ),
)

_ID6 = "name_becomes_duplicated"
NAME_BECOMES_DUPLICATED = Scenario(
    id=_ID6,
    title="A name defined in both branches of a try is present, but ambiguous -- not removed",
    prd_refs=("ADR-0005", "DRF-3"),
    commits=(
        Commit(
            "c1", "Single definition", {**package(_ID6), _src(_ID6, "api"): "def f(a=1): ...\n"}
        ),
        Commit(
            "c2",
            "Define it in both branches of a try",
            {
                _src(_ID6, "api"): text("""
                try:
                    def f(a=1): ...
                except ImportError:
                    def f(a=2): ...
            """)
            },
        ),
        Commit("c3", "Back to one definition", {_src(_ID6, "api"): "def f(a=1): ...\n"}),
    ),
    expectations=(),
    states=(
        _state(_ID6, "c1", "api.f", True, kind="function"),
        _state(_ID6, "c2", "api.f", True, kind="ambiguous"),
        _state(_ID6, "c3", "api.f", True, kind="function"),
    ),
)

_ID7 = "class_becomes_ambiguous"
CLASS_BECOMES_AMBIGUOUS = Scenario(
    id=_ID7,
    title="When a class becomes ambiguous its members are unknowable, not removed",
    prd_refs=("ADR-0005",),
    commits=(
        Commit(
            "c1",
            "One class",
            {**package(_ID7), _src(_ID7, "api"): "class C:\n    def m(self): ...\n"},
        ),
        Commit(
            "c2",
            "Define the class twice",
            {_src(_ID7, "api"): "class C:\n    def m(self): ...\n\n\nclass C:\n    x = 1\n"},
        ),
        Commit("c3", "One class again", {_src(_ID7, "api"): "class C:\n    def m(self): ...\n"}),
    ),
    expectations=(),
    states=(
        _state(_ID7, "c2", "api.C", True, kind="ambiguous"),
        _state(_ID7, "c2", "api.C.m", True),
        _state(_ID7, "c3", "api.C", True, kind="class"),
        _state(_ID7, "c3", "api.C.m", True),
    ),
)

_ID8 = "submodule_import_collision"
SUBMODULE_IMPORT_COLLISION = Scenario(
    id=_ID8,
    title="`from . import sub` shares a key with the sub module: the module owns it",
    prd_refs=("ADR-0005",),
    commits=(
        Commit(
            "c1",
            "Add sub",
            {**package(_ID8), _src(_ID8, "sub"): "def f(): ...\n"},
        ),
        Commit(
            "c2",
            "Import it in the package",
            {f"src/{_ID8}/__init__.py": '"""pkg."""\nfrom . import sub\n'},
        ),
        Commit("c3", "Edit sub", {_src(_ID8, "sub"): "def f(): ...\n\n\ndef g(): ...\n"}),
    ),
    expectations=(),
    states=tuple(
        _state(_ID8, label, "sub", True, kind="module", defined_at=_src(_ID8, "sub"))
        for label in ("c1", "c2", "c3")
    ),
)

_ID9 = "submodule_import_alias_first"
SUBMODULE_IMPORT_ALIAS_FIRST = Scenario(
    id=_ID9,
    title="The alias arrives before the module exists, then the module takes the key over",
    prd_refs=("ADR-0005",),
    commits=(
        Commit(
            "c1",
            "Import a sub module that does not exist yet",
            {f"src/{_ID9}/__init__.py": '"""pkg."""\nfrom . import sub\n'},
        ),
        Commit("c2", "Add the module", {_src(_ID9, "sub"): "def f(): ...\n"}),
    ),
    expectations=(),
    states=(
        _state(_ID9, "c1", "sub", True, kind="attribute", defined_at=f"src/{_ID9}/__init__.py"),
        _state(_ID9, "c2", "sub", True, kind="module", defined_at=_src(_ID9, "sub")),
    ),
)

_ID10 = "symbol_returns"
SYMBOL_RETURNS = Scenario(
    id=_ID10,
    title="A removed symbol that is added back is present again",
    prd_refs=("ADR-0005",),
    commits=(
        Commit("c1", "Define f", {**package(_ID10), _src(_ID10, "api"): "def f(): ...\n"}),
        Commit("c2", "Remove f", {_src(_ID10, "api"): "x = 1\n"}),
        Commit("c3", "Add f back", {_src(_ID10, "api"): "def f(): ...\n"}),
    ),
    expectations=(),
    states=(
        _state(_ID10, "c1", "api.f", True),
        _state(_ID10, "c2", "api.f", False),
        _state(_ID10, "c3", "api.f", True, kind="function"),
    ),
)

SCENARIOS: tuple[Scenario, ...] = (
    FILE_DELETED,
    CLASS_REMOVED_WITH_MEMBERS,
    FILE_RENAMED,
    LAYOUT_MOVE_SAME_KEY,
    SYNTAX_ERROR_EDIT,
    NAME_BECOMES_DUPLICATED,
    CLASS_BECOMES_AMBIGUOUS,
    SUBMODULE_IMPORT_COLLISION,
    SUBMODULE_IMPORT_ALIAS_FIRST,
    SYMBOL_RETURNS,
)
