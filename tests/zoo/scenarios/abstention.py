"""Scenarios where the right answer is *not* to report drift (PRD §7.4, DRF-3, DRF-5)."""

from __future__ import annotations

from ..model import ClosureExpectation, Commit, Expectation, Layer, Outcome, Scenario
from ._util import package, sym, text

_ID1 = "dynamic_module_getattr"
DYNAMIC_MODULE_GETATTR = Scenario(
    id=_ID1,
    title="README mentions a symbol in a module that resolves attributes dynamically",
    prd_refs=("§14#6", "DRF-3"),
    commits=(
        Commit(
            "c1",
            "Add a plugins module with a module-level __getattr__",
            {
                **package(_ID1),
                f"src/{_ID1}/plugins.py": text("""
                    def __getattr__(name):
                        raise AttributeError(name)
                """),
                "README.md": f"Use `{_ID1}.plugins.fancy` for fancy things.\n",
            },
        ),
    ),
    expectations=(
        Expectation(
            "c1",
            sym(_ID1, "plugins.fancy"),
            "exists",
            Layer.L2,
            Outcome.ABSTAIN,
            code_value=None,
            claims=(("plumb-readme", "true"),),
            note="Never project 'false' for exists in a dynamic module; stays unverified.",
        ),
    ),
    closures=(ClosureExpectation("c1", sym(_ID1, "plugins"), closed=False),),
)

_ID2 = "kwargs_abstention"
KWARGS_ABSTENTION = Scenario(
    id=_ID2,
    title="README passes timeout=5 to a function that takes **options",
    prd_refs=("DRF-3",),
    commits=(
        Commit(
            "c1",
            "Add connect(host, **options)",
            {
                **package(_ID2),
                f"src/{_ID2}/client.py": text("""
                    def connect(host, **options):
                        return host, options
                """),
                "README.md": text("""
                    ```python
                    connect("db", timeout=5)
                    ```
                """),
            },
        ),
    ),
    expectations=(
        Expectation(
            "c1",
            sym(_ID2, "client.connect"),
            "param.timeout.exists",
            Layer.L2,
            Outcome.ABSTAIN,
            code_value=None,
            claims=(("plumb-readme", "true"),),
            note="With **kwargs present the projector must not assert 'false' (DRF-3).",
        ),
    ),
)

_ID3 = "ambiguous_reference"
AMBIGUOUS_REFERENCE = Scenario(
    id=_ID3,
    title="README names `connect` but two modules define it",
    prd_refs=("ING-6",),
    commits=(
        Commit(
            "c1",
            "Two connect functions and an unqualified README mention",
            {
                **package(_ID3),
                f"src/{_ID3}/a.py": "def connect():\n    return 'a'\n",
                f"src/{_ID3}/b.py": "def connect():\n    return 'b'\n",
                "README.md": "Call `connect` to open a connection.\n",
            },
        ),
    ),
    expectations=tuple(
        Expectation(
            "c1",
            sym(_ID3, f"{module}.connect"),
            "exists",
            Layer.L2,
            Outcome.UNDOCUMENTED,
            note="An unqualified, ambiguous reference yields no claim at all (ING-6).",
        )
        for module in ("a", "b")
    ),
)

_ID4 = "raises_corroboration_only"
RAISES_CORROBORATION_ONLY = Scenario(
    id=_ID4,
    title="Docstring lists two exceptions; the code visibly raises only one",
    prd_refs=("§7.4", "R3"),
    commits=(
        Commit(
            "c1",
            "Add fetch with a Raises section",
            {
                **package(_ID4),
                f"src/{_ID4}/store.py": text('''
                    def fetch(key):
                        """Fetch ``key``.

                        Raises:
                            KeyError: If ``key`` is missing.
                            TimeoutError: If the backend is too slow.
                        """
                        if not key:
                            raise KeyError(key)
                        return key
                '''),
            },
        ),
    ),
    expectations=(
        Expectation(
            "c1",
            sym(_ID4, "store.fetch"),
            "raises.KeyError",
            Layer.L2,
            Outcome.CORROBORATE,
            code_value="true",
            claims=(("plumb-docstring", "true"),),
            note="A direct `raise KeyError` earns a verified badge.",
        ),
        Expectation(
            "c1",
            sym(_ID4, "store.fetch"),
            "raises.TimeoutError",
            Layer.L2,
            Outcome.ABSTAIN,
            code_value=None,
            claims=(("plumb-docstring", "true"),),
            note="Absence of a raise can't be proven, so it never projects 'false' (R3).",
        ),
    ),
)

_ID5 = "adr_superseded"
ADR_SUPERSEDED = Scenario(
    id=_ID5,
    title="A superseded ADR states an old default; ADRs yield no claims",
    prd_refs=("§14#8", "ING-4"),
    commits=(
        Commit(
            "c1",
            "Record ADR-0005, then supersede it with ADR-0007",
            {
                **package(_ID5),
                f"src/{_ID5}/client.py": text("""
                    def connect(host, timeout=60):
                        return host, timeout
                """),
                "docs/adr/ADR-0005.md": text("""
                    # ADR-0005: Default timeout

                    Status: Superseded by ADR-0007

                    The `connect` timeout defaults to 30 seconds.
                """),
                "docs/adr/ADR-0007.md": text("""
                    # ADR-0007: Default timeout, revised

                    Status: Accepted

                    The `connect` timeout defaults to 60 seconds.
                """),
            },
        ),
    ),
    expectations=(
        Expectation(
            "c1",
            sym(_ID5, "client.connect"),
            "param.timeout.default",
            Layer.L2,
            Outcome.UNDOCUMENTED,
            note="ADRs are historical records; extracting claims would manufacture drift (ING-4).",
        ),
    ),
)

SCENARIOS: tuple[Scenario, ...] = (
    DYNAMIC_MODULE_GETATTR,
    KWARGS_ABSTENTION,
    AMBIGUOUS_REFERENCE,
    RAISES_CORROBORATION_ONLY,
    ADR_SUPERSEDED,
)
