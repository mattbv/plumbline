"""Scenarios about when absence is provable (ADR-0003, DRF-3).

Each one documents a member of a module or class that the importer never sees
defined. Whether that is *drift* (the namespace is closed, so the name really
is absent) or merely *unverified* (something could still supply it) is exactly
what `namespace_closed` decides.
"""

from __future__ import annotations

from ..model import ClosureExpectation, Commit, DriftClass, Expectation, Layer, Outcome, Scenario
from ._util import package, sym, text


def _readme(scenario_id: str, *members: str) -> str:
    lines = [f"- `{scenario_id}.api.{member}`" for member in members]
    return "# Reference\n\n" + "\n".join(lines) + "\n"


def _scenario(
    scenario_id: str,
    title: str,
    api: str,
    documented: tuple[str, ...],
    expectations: tuple[Expectation, ...],
    closures: tuple[ClosureExpectation, ...],
) -> Scenario:
    return Scenario(
        id=scenario_id,
        title=title,
        prd_refs=("ADR-0003", "DRF-3"),
        commits=(
            Commit(
                "c1",
                "Add api and document it",
                {
                    **package(scenario_id),
                    f"src/{scenario_id}/api.py": api,
                    "README.md": _readme(scenario_id, *documented),
                },
            ),
        ),
        expectations=expectations,
        closures=closures,
    )


def _exists(scenario_id: str, member: str, outcome: Outcome, **kwargs: object) -> Expectation:
    return Expectation(
        "c1",
        sym(scenario_id, f"api.{member}"),
        "exists",
        Layer.L2,
        outcome,
        **kwargs,  # type: ignore[arg-type]
    )


def _closure(
    scenario_id: str, member: str | None, closed: bool, note: str = ""
) -> ClosureExpectation:
    dotted = "api" if member is None else f"api.{member}"
    return ClosureExpectation("c1", sym(scenario_id, dotted), closed, note)


_ID1 = "closed_module_missing_member"
CLOSED_MODULE_MISSING_MEMBER = _scenario(
    _ID1,
    "Docs name a function a plain module never defined: absence is provable, so it is drift",
    text("""
        def connect():
            return 1
    """),
    ("connect", "old"),
    (
        _exists(
            _ID1,
            "connect",
            Outcome.CORROBORATE,
            code_value="true",
            claims=(("plumb-readme", "true"),),
        ),
        _exists(
            _ID1,
            "old",
            Outcome.CONTRADICT,
            code_value="false",
            claims=(("plumb-readme", "true"),),
            drift_class=DriftClass.DOC_VS_CODE,
            note="Positive control: a closed namespace lets the projector assert absence.",
        ),
    ),
    (_closure(_ID1, None, True),),
)

_ID2 = "module_alias_binding"
MODULE_ALIAS_BINDING = _scenario(
    _ID2,
    "An alias assigned at module level is a real attribute, not a missing name",
    text("""
        def _connect():
            return 1


        connect = _connect
    """),
    ("connect",),
    (
        _exists(
            _ID2,
            "connect",
            Outcome.CORROBORATE,
            code_value="true",
            claims=(("plumb-readme", "true"),),
            note="Without bound-name facts the projector would call this drift (ADR-0003).",
        ),
    ),
    (_closure(_ID2, None, True),),
)

_ID3 = "module_star_import_open"
MODULE_STAR_IMPORT_OPEN = _scenario(
    _ID3,
    "A star import may supply any name; the importer cannot see them",
    "from os.path import *\n",
    ("join",),
    (_exists(_ID3, "join", Outcome.ABSTAIN, code_value=None, claims=(("plumb-readme", "true"),)),),
    (_closure(_ID3, None, False, "`import *` hides the names it brings in."),),
)

_ID4 = "module_namespace_write_open"
MODULE_NAMESPACE_WRITE_OPEN = _scenario(
    _ID4,
    "The module registers a name at import time through globals()",
    'globals()["dynamic_name"] = 1\n',
    ("dynamic_name",),
    (
        _exists(
            _ID4,
            "dynamic_name",
            Outcome.ABSTAIN,
            code_value=None,
            claims=(("plumb-readme", "true"),),
        ),
    ),
    (_closure(_ID4, None, False),),
)

_ID5 = "class_external_base_open"
CLASS_EXTERNAL_BASE_OPEN = _scenario(
    _ID5,
    "A documented method may be inherited from a base the importer was never shown",
    text("""
        from lib import BaseClient


        class Client(BaseClient):
            def connect(self):
                return 1
    """),
    ("Client.close",),
    (
        _exists(
            _ID5,
            "Client.close",
            Outcome.ABSTAIN,
            code_value=None,
            claims=(("plumb-readme", "true"),),
        ),
    ),
    (
        _closure(_ID5, None, True, "The module itself is fine; only the class is open."),
        _closure(_ID5, "Client", False),
    ),
)

_ID6 = "class_in_file_base_open"
CLASS_IN_FILE_BASE_OPEN = _scenario(
    _ID6,
    "An inherited method is real even when its base is in the same file",
    text("""
        class Base:
            def close(self):
                return 1


        class Child(Base):
            def connect(self):
                return 2
    """),
    ("Child.close",),
    (
        _exists(
            _ID6,
            "Child.close",
            Outcome.ABSTAIN,
            code_value=None,
            claims=(("plumb-readme", "true"),),
        ),
    ),
    (
        _closure(_ID6, "Base", True),
        _closure(
            _ID6, "Child", False, "Inheritance is not modelled yet, so any base opens the class."
        ),
    ),
)

_ID7 = "class_instance_attribute"
CLASS_INSTANCE_ATTRIBUTE = _scenario(
    _ID7,
    "An attribute set in __init__ is a member even though no def or class creates it",
    text("""
        class Client:
            def __init__(self, timeout=5):
                self.timeout = timeout
    """),
    ("Client.timeout",),
    (
        _exists(
            _ID7,
            "Client.timeout",
            Outcome.CORROBORATE,
            code_value="true",
            claims=(("plumb-readme", "true"),),
        ),
    ),
    (_closure(_ID7, "Client", True),),
)

_ID8 = "class_getattr_open"
CLASS_GETATTR_OPEN = _scenario(
    _ID8,
    "A proxy class resolves attributes at runtime",
    text("""
        class Proxy:
            def __getattr__(self, name):
                return name
    """),
    ("Proxy.anything",),
    (
        _exists(
            _ID8,
            "Proxy.anything",
            Outcome.ABSTAIN,
            code_value=None,
            claims=(("plumb-readme", "true"),),
        ),
    ),
    (_closure(_ID8, "Proxy", False),),
)

SCENARIOS: tuple[Scenario, ...] = (
    CLOSED_MODULE_MISSING_MEMBER,
    MODULE_ALIAS_BINDING,
    MODULE_STAR_IMPORT_OPEN,
    MODULE_NAMESPACE_WRITE_OPEN,
    CLASS_EXTERNAL_BASE_OPEN,
    CLASS_IN_FILE_BASE_OPEN,
    CLASS_INSTANCE_ATTRIBUTE,
    CLASS_GETATTR_OPEN,
)
