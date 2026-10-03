"""Scenarios about signatures, defaults, and types (PRD §14 #1-#4, #10, #11)."""

from __future__ import annotations

from plumbline.domain.dispositions import Disposition

from ..model import Commit, DriftClass, Expectation, Layer, Outcome, Scenario
from ._util import package, sym, text


def _connect(default: int, doc_default: int | None = None) -> str:
    shown = default if doc_default is None else doc_default
    return text(f'''
        def connect(host, timeout={default}):
            """Open a connection to ``host``.

            Args:
                host: Host name.
                timeout: Seconds to wait. Defaults to {shown}.
            """
            return host, timeout
    ''')


def _readme_table(default: int) -> str:
    return text(f"""
        # Client

        | Parameter | Default |
        |-----------|---------|
        | `timeout` | `{default}` |
    """)


_ID1 = "sig_change_docs_updated"
SIG_CHANGE_DOCS_UPDATED = Scenario(
    id=_ID1,
    title="Default changes 30 -> 60 and every source is updated in the same commit",
    prd_refs=("§14#1",),
    commits=(
        Commit(
            "c1",
            "Add connect with a 30s timeout",
            {
                **package(_ID1),
                f"src/{_ID1}/client.py": _connect(30),
                "README.md": _readme_table(30),
            },
        ),
        Commit(
            "c2",
            "Raise the timeout default to 60 and update the docs",
            {f"src/{_ID1}/client.py": _connect(60), "README.md": _readme_table(60)},
        ),
    ),
    expectations=(
        Expectation(
            "c1",
            sym(_ID1, "client.connect"),
            "param.timeout.default",
            Layer.L2,
            Outcome.CORROBORATE,
            code_value="30",
            claims=(("plumb-docstring", "30"), ("plumb-readme", "30")),
        ),
        Expectation(
            "c2",
            sym(_ID1, "client.connect"),
            "param.timeout.default",
            Layer.L1,
            Outcome.SUPERSEDE,
            code_value="60",
            previous_code_value="30",
            note="Code evolving is expected: the 30 window closes, no review (§7.1).",
        ),
        Expectation(
            "c2",
            sym(_ID1, "client.connect"),
            "param.timeout.default",
            Layer.L2,
            Outcome.CORROBORATE,
            code_value="60",
            claims=(("plumb-docstring", "60"), ("plumb-readme", "60")),
            note="Old projection and old claims retract; new ones corroborate (§14#1).",
        ),
    ),
)

_ID2 = "sig_change_docs_stale"
SIG_CHANGE_DOCS_STALE = Scenario(
    id=_ID2,
    title="Default changes 30 -> 60 but the README table still says 30",
    prd_refs=("§14#2", "DRF-4"),
    commits=(
        Commit(
            "c1",
            "Add connect with a 30s timeout",
            {
                **package(_ID2),
                f"src/{_ID2}/client.py": text("""
                    def connect(host, timeout=30):
                        return host, timeout
                """),
                "README.md": _readme_table(30),
            },
        ),
        Commit(
            "c2",
            "Raise the timeout default to 60",
            {
                f"src/{_ID2}/client.py": text("""
                def connect(host, timeout=60):
                    return host, timeout
            """)
            },
        ),
    ),
    expectations=(
        Expectation(
            "c1",
            sym(_ID2, "client.connect"),
            "param.timeout.default",
            Layer.L2,
            Outcome.CORROBORATE,
            code_value="30",
            claims=(("plumb-readme", "30"),),
        ),
        Expectation(
            "c2",
            sym(_ID2, "client.connect"),
            "param.timeout.default",
            Layer.L1,
            Outcome.SUPERSEDE,
            code_value="60",
            previous_code_value="30",
        ),
        Expectation(
            "c2",
            sym(_ID2, "client.connect"),
            "param.timeout.default",
            Layer.L2,
            Outcome.CONTRADICT,
            code_value="60",
            claims=(("plumb-readme", "30"),),
            drift_class=DriftClass.DOC_VS_CODE,
            disposition=Disposition.DOCS_STALE,
            note="Drift introduced by c2: the README claim 30 meets the new projection 60.",
        ),
    ),
)

_ID3 = "three_way_default_disagreement"
THREE_WAY_DEFAULT_DISAGREEMENT = Scenario(
    id=_ID3,
    title="Code, docstring and README say 30; a docs page says 45",
    prd_refs=("§14#3", "DRF-4"),
    commits=(
        Commit(
            "c1",
            "Document the timeout in three places, one of them wrong",
            {
                **package(_ID3),
                f"src/{_ID3}/client.py": _connect(30),
                "README.md": _readme_table(30),
                "docs/tuning.md": text("""
                    # Tuning

                    | Parameter | Default |
                    |-----------|---------|
                    | `timeout` | `45` |
                """),
            },
        ),
    ),
    expectations=(
        Expectation(
            "c1",
            sym(_ID3, "client.connect"),
            "param.timeout.default",
            Layer.L2,
            Outcome.CONTRADICT,
            code_value="30",
            claims=(("plumb-docstring", "30"), ("plumb-readme", "30"), ("plumb-docs", "45")),
            drift_class=DriftClass.DOC_VS_DOC_VS_CODE,
            disposition=Disposition.DOCS_STALE,
            note="Three members plus the projection; README agrees, docs page is stale (§14#3).",
        ),
    ),
)

_ID4 = "code_defect_regression"


def _parse(default: str) -> str:
    return text(f'''
        def parse(text, strict={default}):
            """Parse ``text``.

            Args:
                text: Input.
                strict: Reject unknown keys. Defaults to True.
            """
            return text, strict
    ''')


CODE_DEFECT_REGRESSION = Scenario(
    id=_ID4,
    title="A refactor flips strict=True to False while three doc sources still say True",
    prd_refs=("§14#4", "§7.6"),
    commits=(
        Commit(
            "c1",
            "Add parse with strict=True",
            {
                **package(_ID4),
                f"src/{_ID4}/parser.py": _parse("True"),
                "README.md": text("""
                    | Parameter | Default |
                    |-----------|---------|
                    | `strict` | `True` |
                """),
                "docs/parsing.md": text("""
                    # Parsing

                    | Parameter | Default |
                    |-----------|---------|
                    | `strict` | `True` |
                """),
            },
        ),
        Commit("c2", "Refactor parser defaults", {f"src/{_ID4}/parser.py": _parse("False")}),
    ),
    expectations=(
        Expectation(
            "c1",
            sym(_ID4, "parser.parse"),
            "param.strict.default",
            Layer.L2,
            Outcome.CORROBORATE,
            code_value="True",
            claims=(
                ("plumb-docs", "True"),
                ("plumb-docstring", "True"),
                ("plumb-readme", "True"),
            ),
        ),
        Expectation(
            "c2",
            sym(_ID4, "parser.parse"),
            "param.strict.default",
            Layer.L1,
            Outcome.SUPERSEDE,
            code_value="False",
            previous_code_value="True",
        ),
        Expectation(
            "c2",
            sym(_ID4, "parser.parse"),
            "param.strict.default",
            Layer.L2,
            Outcome.CONTRADICT,
            code_value="False",
            claims=(
                ("plumb-docs", "True"),
                ("plumb-docstring", "True"),
                ("plumb-readme", "True"),
            ),
            drift_class=DriftClass.DOC_VS_CODE,
            disposition=Disposition.CODE_DEFECT,
            note="Docs agree with each other; a reviewer should rule the code the defect (§14#4).",
        ),
    ),
)

_ID5 = "kwarg_removed"
KWARG_REMOVED = Scenario(
    id=_ID5,
    title="A keyword argument is removed but the README example still passes it",
    prd_refs=("§7.4", "DRF-4"),
    commits=(
        Commit(
            "c1",
            "Add connect(host, timeout)",
            {
                **package(_ID5),
                f"src/{_ID5}/client.py": text("""
                    def connect(host, timeout=5):
                        return host, timeout
                """),
                "README.md": text("""
                    # Usage

                    ```python
                    connect("db", timeout=5)
                    ```
                """),
            },
        ),
        Commit(
            "c2",
            "Drop the timeout parameter",
            {
                f"src/{_ID5}/client.py": text("""
                def connect(host):
                    return host
            """)
            },
        ),
    ),
    expectations=(
        Expectation(
            "c1",
            sym(_ID5, "client.connect"),
            "param.timeout.exists",
            Layer.L2,
            Outcome.CORROBORATE,
            code_value="true",
            claims=(("plumb-readme", "true"),),
        ),
        Expectation(
            "c2",
            sym(_ID5, "client.connect"),
            "param.timeout.exists",
            Layer.L1,
            Outcome.SUPERSEDE,
            code_value="false",
            previous_code_value="true",
        ),
        Expectation(
            "c2",
            sym(_ID5, "client.connect"),
            "param.timeout.exists",
            Layer.L2,
            Outcome.CONTRADICT,
            code_value="false",
            claims=(("plumb-readme", "true"),),
            drift_class=DriftClass.DOC_VS_CODE,
            disposition=Disposition.DOCS_STALE,
            note="No **kwargs, so the projector may assert 'false' (DRF-3).",
        ),
    ),
)

_ID6 = "type_omits_none"
TYPE_OMITS_NONE = Scenario(
    id=_ID6,
    title="Docstring says timeout is int; the annotation is int | None",
    prd_refs=("§14#10",),
    commits=(
        Commit(
            "c1",
            "Add connect with an optional timeout",
            {
                **package(_ID6),
                f"src/{_ID6}/client.py": text('''
                    def connect(host: str, timeout: int | None = None) -> None:
                        """Open a connection.

                        Args:
                            host (str): Host name.
                            timeout (int): Seconds to wait.
                        """
                '''),
            },
        ),
    ),
    expectations=(
        Expectation(
            "c1",
            sym(_ID6, "client.connect"),
            "param.timeout.type",
            Layer.L2,
            Outcome.CONTRADICT,
            code_value="None | int",
            claims=(("plumb-docstring", "int"),),
            drift_class=DriftClass.DOC_VS_CODE,
            note=(
                "Real drift: the docs omit None. A team that finds this noisy waives it per "
                "fact (intentional_simplification) or disables the type aspect (§14#10)."
            ),
        ),
        Expectation(
            "c1",
            sym(_ID6, "client.connect"),
            "param.host.type",
            Layer.L2,
            Outcome.CORROBORATE,
            code_value="str",
            claims=(("plumb-docstring", "str"),),
        ),
    ),
)

_ID7 = "requires_python_bump"
_PROJECT7 = f"project:{_ID7}"


def _pyproject(spec: str) -> str:
    return f'[project]\nname = "{_ID7}"\nrequires-python = "{spec}"\n'


REQUIRES_PYTHON_BUMP = Scenario(
    id=_ID7,
    title="requires-python is bumped to >=3.11 while the README still says 3.9+",
    prd_refs=("§14#11",),
    commits=(
        Commit(
            "c1",
            "Initial release supporting 3.9",
            {
                "pyproject.toml": _pyproject(">=3.9"),
                "README.md": "# Install\n\nRequires Python 3.9+.\n",
            },
        ),
        Commit("c2", "Drop 3.9 and 3.10", {"pyproject.toml": _pyproject(">=3.11")}),
    ),
    expectations=(
        Expectation(
            "c1",
            _PROJECT7,
            "project.requires_python",
            Layer.L2,
            Outcome.CORROBORATE,
            code_value=">=3.9",
            claims=(("plumb-readme", ">=3.9"),),
        ),
        Expectation(
            "c2",
            _PROJECT7,
            "project.requires_python",
            Layer.L1,
            Outcome.SUPERSEDE,
            code_value=">=3.11",
            previous_code_value=">=3.9",
        ),
        Expectation(
            "c2",
            _PROJECT7,
            "project.requires_python",
            Layer.L2,
            Outcome.CONTRADICT,
            code_value=">=3.11",
            claims=(("plumb-readme", ">=3.9"),),
            drift_class=DriftClass.DOC_VS_CODE,
            disposition=Disposition.DOCS_STALE,
            note="Surfaced the moment the bump landed (§14#11).",
        ),
    ),
)

_ID8 = "drift_persists"
DRIFT_PERSISTS = Scenario(
    id=_ID8,
    title="An open contradiction survives unrelated later commits and keeps its origin",
    prd_refs=("DRF-4", "§7.6"),
    commits=(
        Commit(
            "c1",
            "Add connect with a 30s timeout",
            {
                **package(_ID8),
                f"src/{_ID8}/client.py": text("""
                    def connect(host, timeout=30):
                        return host, timeout
                """),
                "README.md": _readme_table(30),
                "NOTES.md": "Scratch notes.\n",
            },
        ),
        Commit(
            "c2",
            "Raise the timeout default to 60",
            {
                f"src/{_ID8}/client.py": text("""
                def connect(host, timeout=60):
                    return host, timeout
            """)
            },
        ),
        Commit("c3", "Edit unrelated notes", {"NOTES.md": "More scratch notes.\n"}),
    ),
    expectations=(
        Expectation(
            "c2",
            sym(_ID8, "client.connect"),
            "param.timeout.default",
            Layer.L2,
            Outcome.CONTRADICT,
            code_value="60",
            claims=(("plumb-readme", "30"),),
            drift_class=DriftClass.DOC_VS_CODE,
        ),
        Expectation(
            "c3",
            sym(_ID8, "client.connect"),
            "param.timeout.default",
            Layer.L2,
            Outcome.CONTRADICT,
            code_value="60",
            claims=(("plumb-readme", "30"),),
            drift_class=DriftClass.DOC_VS_CODE,
            introduced_in="c2",
            note="No auto-resolution: it stays open and still points at c2 (PRD §7.6).",
        ),
    ),
)

_TS = "plumb-docstring"


def _typed_scenario(
    scenario_id: str,
    title: str,
    source: str,
    expectations: tuple[tuple[str, str, Outcome, str, str, DriftClass | None, str], ...],
) -> Scenario:
    """One commit with one module, and L2 expectations ``(symbol tail, aspect, outcome,
    code value, doc value, drift class, note)``. For an ABSTAIN the code value is the one the
    importer states and the projector withholds."""
    return Scenario(
        id=scenario_id,
        title=title,
        prd_refs=("§14#10",),
        commits=(
            Commit(
                "c1",
                "Add the module",
                {**package(scenario_id), f"src/{scenario_id}/m.py": text(source)},
            ),
        ),
        expectations=tuple(
            Expectation(
                "c1", sym(scenario_id, tail), aspect, Layer.L2, outcome,
                code_value=None if outcome is Outcome.ABSTAIN else code,
                withheld_value=code if outcome is Outcome.ABSTAIN else None,
                claims=((_TS, doc),), drift_class=drift, note=note,
            )
            for tail, aspect, outcome, code, doc, drift, note in expectations
        ),
    )  # fmt: skip


TYPE_REPRESENTATION_ONLY = _typed_scenario(
    "type_representation_only",
    "Docs and annotations spell the same types differently: quotes, List, Optional",
    '''
    from typing import Dict, List, Optional

    def render(items: List["Segment"], style: Optional[Dict[str, int]] = None) -> None:
        """Render items.

        Args:
            items (list[Segment]): The items.
            style (dict[str, int], optional): A style map.
        """
    ''',
    (
        ("m.render", "param.items.type", Outcome.CORROBORATE,
         "list[Segment]", "list[Segment]", None,
         "A quoted forward reference and a typing.List are the same type as the docs' spelling."),
        ("m.render", "param.style.type", Outcome.CORROBORATE, "None | dict[str, int]",
         "None | dict[str, int]", None,
         "`(dict[str, int], optional)` states that None is allowed, as `Optional[...]` does."),
    ),
)  # fmt: skip

TYPE_OPTIONAL_BUT_STRICTER = _typed_scenario(
    "type_optional_but_stricter",
    "Docs say `(int, optional)` for a parameter with a default whose annotation is plain int",
    '''
    def retry(count: int = 5) -> None:
        """Retry.

        Args:
            count (int, optional): How many times.
        """
    ''',
    (
        ("m.retry", "param.count.type", Outcome.ABSTAIN, "int", "None | int", None,
         "`optional` means omittable here, not nullable: the docs permit more than the code "
         "does, which is not provably wrong."),
    ),
)  # fmt: skip

TYPE_ALIAS_ABSTAINS = _typed_scenario(
    "type_alias_abstains",
    "The annotation is a name the analysis cannot resolve; the docs give its base type",
    '''
    from typing import Literal

    JustifyMethod = Literal["left", "right", "center"]

    def align(mode: JustifyMethod = "left") -> None:
        """Align.

        Args:
            mode (str): One of left, right or center.
        """
    ''',
    (
        ("m.align", "param.mode.type", Outcome.ABSTAIN, "JustifyMethod", "str", None,
         "JustifyMethod may be an alias for a case of str; that cannot be told from here."),
    ),
)  # fmt: skip

TYPE_BARE_GENERIC = _typed_scenario(
    "type_bare_generic",
    "Docs name `Callable`; the annotation gives its parameters",
    '''
    from typing import Callable

    def on_event(handler: Callable[[int], str]) -> None:
        """Register.

        Args:
            handler (Callable): The handler.
        """
    ''',
    (
        ("m.on_event", "param.handler.type", Outcome.ABSTAIN,
         "Callable[[int], str]", "Callable", None,
         "The docs left the parameters out; that is brevity, not disagreement."),
    ),
)  # fmt: skip

TYPE_RESOLVED_DISAGREEMENT = _typed_scenario(
    "type_resolved_disagreement",
    "Docs and annotations disagree, using only types the analysis can resolve",
    '''
    from typing import Iterable

    def total(count: int, ids: Iterable[int]) -> None:
        """Total.

        Args:
            count (str): How many.
            ids (List[int]): The ids.
        """
    ''',
    (
        ("m.total", "param.count.type", Outcome.CONTRADICT, "int", "str", DriftClass.DOC_VS_CODE,
         "int against str is a provable disagreement."),
        ("m.total", "param.ids.type", Outcome.CONTRADICT, "Iterable[int]", "list[int]",
         DriftClass.DOC_VS_CODE, "The docs promise a list; the code accepts any iterable."),
    ),
)  # fmt: skip

DEFAULT_FORMS = _typed_scenario(
    "default_forms",
    "Defaults written as `100` for a float, and a sentence that quotes the word default",
    '''
    def scale(total: float = 100.0, justify=None) -> None:
        """Scale.

        Args:
            total (float): The total. Defaults to 100.
            justify (str): One of "default", "left" or "right". Defaults to None.
        """
    ''',
    (
        ("m.scale", "param.total.default", Outcome.CORROBORATE, "100", "100", None,
         "100 and 100.0 are the same default."),
        ("m.scale", "param.justify.default", Outcome.CORROBORATE, "None", "None", None,
         'The quoted word "default" is a value in the sentence, not the keyword.'),
    ),
)  # fmt: skip


SCENARIOS: tuple[Scenario, ...] = (
    SIG_CHANGE_DOCS_UPDATED,
    SIG_CHANGE_DOCS_STALE,
    THREE_WAY_DEFAULT_DISAGREEMENT,
    CODE_DEFECT_REGRESSION,
    KWARG_REMOVED,
    TYPE_OMITS_NONE,
    TYPE_REPRESENTATION_ONLY,
    TYPE_OPTIONAL_BUT_STRICTER,
    TYPE_ALIAS_ABSTAINS,
    TYPE_BARE_GENERIC,
    TYPE_RESOLVED_DISAGREEMENT,
    DEFAULT_FORMS,
    REQUIRES_PYTHON_BUMP,
    DRIFT_PERSISTS,
)
