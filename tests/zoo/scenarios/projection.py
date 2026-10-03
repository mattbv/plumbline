"""Scenarios aimed at the drift projector's rules and abstentions (ADR-0007)."""

from __future__ import annotations

from ..model import Commit, DriftClass, Expectation, Layer, Outcome, Scenario
from ._util import package, sym, text

_R = "plumb-readme"


def _readme(*rows: str) -> str:
    body = "\n".join(f"| `{name}` | `{value}` |" for name, value in rows)
    return "# Client\n\n| Parameter | Default |\n|---|---|\n" + body + "\n"


def _l2(
    scenario: str, commit: str, member: str, aspect: str, outcome: Outcome, **kw: object
) -> Expectation:
    return Expectation(commit, sym(scenario, member), aspect, Layer.L2, outcome, **kw)  # type: ignore[arg-type]


_ID1 = "decorated_function"
DECORATED_FUNCTION = Scenario(
    id=_ID1,
    title="A decorator may rewrite the signature, so nothing is projected about it",
    prd_refs=("ADR-0007",),
    commits=(
        Commit(
            "c1",
            "A command-decorated function",
            {
                **package(_ID1),
                f"src/{_ID1}/cli.py": text("""
                    @click.command()
                    def connect(host, timeout=30):
                        return host, timeout
                """),
                "README.md": _readme(("timeout", "30")),
            },
        ),
    ),
    expectations=(
        _l2(_ID1, "c1", "cli.connect", "param.timeout.default", Outcome.ABSTAIN,
            code_value=None, claims=((_R, "30"),),
            note="The decorator may add, remove, or reshape parameters: abstain."),
        _l2(_ID1, "c1", "cli.connect", "param.timeout.exists", Outcome.ABSTAIN,
            code_value=None, claims=((_R, "true"),)),
    ),
)  # fmt: skip

_ID2 = "default_not_a_literal"
DEFAULT_NOT_A_LITERAL = Scenario(
    id=_ID2,
    title="A default that is not a plain literal, or a parameter with none, cannot be compared",
    prd_refs=("ADR-0007", "ADR-0004"),
    commits=(
        Commit(
            "c1",
            "Defaults by name, and a required parameter",
            {
                **package(_ID2),
                f"src/{_ID2}/client.py": text("""
                    DEFAULT = 5


                    def connect(host, timeout=DEFAULT):
                        return host, timeout


                    def close(handle):
                        return handle
                """),
                "README.md": _readme(("timeout", "5")),
            },
        ),
    ),
    expectations=(
        _l2(_ID2, "c1", "client.connect", "param.timeout.default", Outcome.ABSTAIN,
            code_value=None, claims=((_R, "5"),),
            note="`DEFAULT` is not a literal: the importer states no default (PRD 7.4)."),
        _l2(_ID2, "c1", "client.close", "param.handle.default", Outcome.ABSTAIN,
            code_value=None, claims=((_R, "1"),),
            note="No default and a non-literal default look the same; never guess (ADR-0007)."),
    ),
)  # fmt: skip

_ID3 = "claim_removed_withdraws_projection"
CLAIM_REMOVED_WITHDRAWS_PROJECTION = Scenario(
    id=_ID3,
    title="When the last doc claim leaves a slot, the code's projection is withdrawn with it",
    prd_refs=("ADR-0007", "DRF-2"),
    commits=(
        Commit(
            "c1",
            "Document the default",
            {
                **package(_ID3),
                f"src/{_ID3}/client.py": "def connect(host, timeout=30):\n    return host\n",
                "README.md": _readme(("timeout", "30")),
            },
        ),
        Commit("c2", "Stop documenting it", {"README.md": "# Client\n"}),
    ),
    expectations=(
        _l2(_ID3, "c1", "client.connect", "param.timeout.default", Outcome.CORROBORATE,
            code_value="30", claims=((_R, "30"),)),
        _l2(_ID3, "c2", "client.connect", "param.timeout.default", Outcome.UNDOCUMENTED,
            note="Nothing to compare: the projection goes too, so the KB tracks the docs."),
    ),
)  # fmt: skip

_CL = "plumb-changelog"
_ID4 = "namespace_opens_and_closes"


def _api(*, dynamic: bool) -> str:
    getattr_ = "\n\ndef __getattr__(name):\n    raise AttributeError(name)\n" if dynamic else ""
    return f"def real():\n    return 1\n{getattr_}"


NAMESPACE_OPENS_AND_CLOSES = Scenario(
    id=_ID4,
    title="A module that gains a __getattr__ can no longer prove a removed name is gone",
    prd_refs=("ADR-0007", "ADR-0003", "§14#6"),
    commits=(
        Commit(
            "c1",
            "A plain module; the changelog says `old` was removed and it is not there",
            {
                **package(_ID4),
                f"src/{_ID4}/api.py": _api(dynamic=False),
                "CHANGELOG.md": "## 2.0\n### Removed\n- `old`\n",
            },
        ),
        Commit("c2", "The module gains a dynamic __getattr__ (CHANGELOG untouched)",
               {f"src/{_ID4}/api.py": _api(dynamic=True)}),
        Commit(
            "c3", "The __getattr__ is removed again", {f"src/{_ID4}/api.py": _api(dynamic=False)}
        ),
    ),
    expectations=(
        _l2(_ID4, "c1", "api.old", "exists", Outcome.CORROBORATE,
            code_value="false", claims=((_CL, "false"),)),
        _l2(_ID4, "c2", "api.old", "exists", Outcome.ABSTAIN,
            code_value=None, claims=((_CL, "false"),),
            note="Only the module changed. The child's projection must still be withdrawn."),
        _l2(_ID4, "c3", "api.old", "exists", Outcome.CORROBORATE,
            code_value="false", claims=((_CL, "false"),),
            note="Closed again: the projection is restored and corroborates."),
    ),
)  # fmt: skip

_ID6 = "dispute_outlives_its_premise"
DISPUTE_OUTLIVES_ITS_PREMISE = Scenario(
    id=_ID6,
    title="When the premise of an open dispute disappears, the dispute stays for a human",
    prd_refs=("ADR-0007", "ADR-0006", "§7.6"),
    commits=(
        Commit(
            "c1",
            "A plain module; the README names a function it never defined",
            {
                **package(_ID6),
                f"src/{_ID6}/api.py": _api(dynamic=False),
                "README.md": f"Call `{_ID6}.api.missing()`.\n",
            },
        ),
        Commit(
            "c2",
            "The module gains a dynamic __getattr__",
            {f"src/{_ID6}/api.py": _api(dynamic=True)},
        ),
        Commit("c3", "The __getattr__ is removed", {f"src/{_ID6}/api.py": _api(dynamic=False)}),
    ),
    expectations=tuple(
        _l2(_ID6, label, "api.missing", "exists", Outcome.CONTRADICT,
            code_value="false", claims=((_R, "true"),), drift_class=DriftClass.DOC_VS_CODE,
            introduced_in="c1",
            note=note)
        for label, note in (
            ("c1", "Drift: the README names something the closed module never defined."),
            ("c2", "The module opened, so this is no longer provable -- but the projector is "
                   "a party to the dispute and may not withdraw it. It stays, deferred."),
            ("c3", "Never resolved: still the dispute that opened at c1."),
        )
    ),
)  # fmt: skip

_ID5 = "fixed_together"
FIXED_TOGETHER = Scenario(
    id=_ID5,
    title="Code and docs fixed in one commit: no false dispute may open mid-commit",
    prd_refs=("ADR-0007", "§14#1"),
    commits=(
        Commit(
            "c1",
            "30 everywhere",
            {
                **package(_ID5),
                f"src/{_ID5}/client.py": "def connect(host, timeout=30):\n    return host\n",
                "README.md": _readme(("timeout", "30")),
            },
        ),
        Commit(
            "c2",
            "60 everywhere, in a single commit",
            {
                f"src/{_ID5}/client.py": "def connect(host, timeout=60):\n    return host\n",
                "README.md": _readme(("timeout", "60")),
            },
        ),
    ),
    expectations=(
        _l2(_ID5, "c1", "client.connect", "param.timeout.default", Outcome.CORROBORATE,
            code_value="30", claims=((_R, "30"),)),
        _l2(_ID5, "c2", "client.connect", "param.timeout.default", Outcome.CORROBORATE,
            code_value="60", claims=((_R, "60"),),
            note="Applied in any other order this opens a false contradiction (ADR-0007)."),
    ),
)  # fmt: skip

SCENARIOS: tuple[Scenario, ...] = (
    DECORATED_FUNCTION,
    DEFAULT_NOT_A_LITERAL,
    CLAIM_REMOVED_WITHDRAWS_PROJECTION,
    NAMESPACE_OPENS_AND_CLOSES,
    DISPUTE_OUTLIVES_ITS_PREMISE,
    FIXED_TOGETHER,
)
