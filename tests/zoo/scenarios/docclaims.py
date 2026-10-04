"""Scenarios about the *claim protocol* for docstrings (ADR-0006).

They are checked against a real KB commit by commit: an edit retracts the old value
before asserting the new one, a removed statement is withdrawn, a deleted file takes
its claims with it, and a file that stops parsing leaves them alone.
"""

from __future__ import annotations

from plumbline.domain.dispositions import Disposition

from ..model import ClaimsExpectation, Commit, DriftClass, Expectation, Layer, Outcome, Scenario
from ._util import package, sym, text

_DS = "plumb-docstring"


def _p(scenario_id: str) -> str:
    return f"src/{scenario_id}/client.py"


def _fn(name: str, doc_default: str | None, *, default: int = 30) -> str:
    """A function whose docstring optionally states the default."""
    said = f" Defaults to {doc_default}." if doc_default is not None else ""
    return text(f'''
        def {name}(host, timeout={default}):
            """Open a connection.

            Args:
                host (str): Host name.
                timeout (int): Seconds to wait.{said}
            """
            return host, timeout
    ''')


def _default(scenario: str, symbol: str, commit: str, value: str | None) -> ClaimsExpectation:
    claims = ((_DS, value),) if value is not None else ()
    return ClaimsExpectation(commit, sym(scenario, symbol), "param.timeout.default", claims)


_ID1 = "docstring_edit"
DOCSTRING_EDIT = Scenario(
    id=_ID1,
    title="Editing a docstring retracts the old claim, then asserts the new one",
    prd_refs=("ADR-0006", "§14#2"),
    commits=(
        Commit("c1", "Document 30", {**package(_ID1), _p(_ID1): _fn("connect", "30")}),
        Commit("c2", "Edit the docstring to say 60", {_p(_ID1): _fn("connect", "60")}),
    ),
    expectations=(
        Expectation(
            "c1", sym(_ID1, "client.connect"), "param.timeout.default", Layer.L2,
            Outcome.CORROBORATE, code_value="30", claims=((_DS, "30"),),
        ),
        Expectation(
            "c2", sym(_ID1, "client.connect"), "param.timeout.default", Layer.L2,
            Outcome.CONTRADICT, code_value="30", claims=((_DS, "60"),),
            drift_class=DriftClass.DOC_VS_CODE, disposition=Disposition.DOCS_STALE,
            note="The docs moved and the code did not: drift introduced by editing the docs.",
        ),
    ),
)  # fmt: skip

_ID2 = "docstring_claim_removed"
DOCSTRING_CLAIM_REMOVED = Scenario(
    id=_ID2,
    title="Dropping 'Defaults to' from a docstring withdraws the claim",
    prd_refs=("ADR-0006",),
    commits=(
        Commit("c1", "Document the default", {**package(_ID2), _p(_ID2): _fn("connect", "30")}),
        Commit("c2", "Stop saying it", {_p(_ID2): _fn("connect", None)}),
    ),
    expectations=(
        Expectation(
            "c2", sym(_ID2, "client.connect"), "param.timeout.default", Layer.L2,
            Outcome.UNDOCUMENTED, code_value="30", claims=(),
            note="Silence is not a claim: with nothing stated there is nothing to dispute.",
        ),
    ),
    claim_states=(_default(_ID2, "client.connect", "c1", "30"),),
)  # fmt: skip

_ID3 = "docstring_function_removed"
DOCSTRING_FUNCTION_REMOVED = Scenario(
    id=_ID3,
    title="Removing a documented function from a file that stays withdraws its claims",
    prd_refs=("ADR-0006", "ADR-0005"),
    commits=(
        Commit(
            "c1", "Two documented functions",
            {**package(_ID3), _p(_ID3): _fn("connect", "30") + "\n\n" + _fn("other", "30")},
        ),
        Commit("c2", "Remove other", {_p(_ID3): _fn("connect", "30")}),
    ),
    expectations=(),
    claim_states=(
        _default(_ID3, "client.connect", "c2", "30"),
        _default(_ID3, "client.other", "c1", "30"),
        _default(_ID3, "client.other", "c2", None),
    ),
)  # fmt: skip

_ID4 = "docstring_file_deleted"
DOCSTRING_FILE_DELETED = Scenario(
    id=_ID4,
    title="Deleting a file withdraws every claim its docstrings made",
    prd_refs=("ADR-0006",),
    commits=(
        Commit("c1", "Document", {**package(_ID4), _p(_ID4): _fn("connect", "30")}),
        Commit("c2", "Delete the module", delete=(_p(_ID4),)),
    ),
    expectations=(),
    claim_states=(
        _default(_ID4, "client.connect", "c1", "30"),
        _default(_ID4, "client.connect", "c2", None),
    ),
)  # fmt: skip

_ID5 = "docstring_syntax_error"
DOCSTRING_SYNTAX_ERROR = Scenario(
    id=_ID5,
    title="A file that stops parsing keeps its claims; they update once it parses again",
    prd_refs=("ADR-0006", "ADR-0005"),
    commits=(
        Commit("c1", "Document 30", {**package(_ID5), _p(_ID5): _fn("connect", "30")}),
        Commit("c2", "Break the syntax", {_p(_ID5): "def connect(:\n"}, broken=(_p(_ID5),)),
        Commit("c3", "Fix it, now saying 60", {_p(_ID5): _fn("connect", "60")}),
    ),
    expectations=(),
    claim_states=(
        _default(_ID5, "client.connect", "c2", "30"),
        _default(_ID5, "client.connect", "c3", "60"),
    ),
)  # fmt: skip

_ID6 = "docstring_function_renamed"
DOCSTRING_FUNCTION_RENAMED = Scenario(
    id=_ID6,
    title="Renaming a documented function moves its claim to the new symbol",
    prd_refs=("ADR-0006", "§14#5"),
    commits=(
        Commit("c1", "Document connect", {**package(_ID6), _p(_ID6): _fn("connect", "30")}),
        Commit("c2", "Rename to open", {_p(_ID6): _fn("open_", "30")}),
    ),
    expectations=(),
    claim_states=(
        _default(_ID6, "client.connect", "c1", "30"),
        _default(_ID6, "client.connect", "c2", None),
        _default(_ID6, "client.open_", "c2", "30"),
    ),
)  # fmt: skip

_ID7 = "docstring_numpy_style"
DOCSTRING_NUMPY_STYLE = Scenario(
    id=_ID7,
    title="NumPy-style sections make the same claims as Google style",
    prd_refs=("ADR-0006", "ING-2"),
    commits=(
        Commit(
            "c1", "NumPy docstring",
            {
                **package(_ID7),
                _p(_ID7): text('''
                    def connect(host, timeout=30):
                        """Open a connection.

                        Parameters
                        ----------
                        host : str
                            Host name.
                        timeout : int, optional
                            Seconds to wait. Default is 30.

                        Returns
                        -------
                        bool
                            Whether it opened.
                        """
                        return True
                '''),
            },
        ),
    ),
    expectations=(
        Expectation(
            "c1", sym(_ID7, "client.connect"), "param.timeout.default", Layer.L2,
            Outcome.CORROBORATE, code_value="30", claims=((_DS, "30"),),
        ),
        Expectation(
            "c1", sym(_ID7, "client.connect"), "param.timeout.type", Layer.L2,
            Outcome.ABSTAIN, code_value=None, claims=((_DS, "None | int"),),
            note="The code has no annotation and the projector never infers types (PRD 7.4).",
        ),
        Expectation(
            "c1", sym(_ID7, "client.connect"), "returns.type", Layer.L2,
            Outcome.ABSTAIN, code_value=None, claims=((_DS, "bool"),),
        ),
    ),
)  # fmt: skip


SCENARIOS: tuple[Scenario, ...] = (
    DOCSTRING_EDIT,
    DOCSTRING_CLAIM_REMOVED,
    DOCSTRING_FUNCTION_REMOVED,
    DOCSTRING_FILE_DELETED,
    DOCSTRING_SYNTAX_ERROR,
    DOCSTRING_FUNCTION_RENAMED,
    DOCSTRING_NUMPY_STYLE,
)
