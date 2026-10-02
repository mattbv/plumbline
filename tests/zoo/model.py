"""Scenario model for the drift zoo.

A `Scenario` is a tiny, self-contained project (its own package, README, docs,
CHANGELOG) that evolves over a few commits, plus the *labeled* outcomes the
Plumbline pipeline is expected to produce for it. Scenarios are pure data:
nothing here touches Git or the filesystem (see `builder.py` for that).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from plumbline.domain.dispositions import Disposition


class Layer(StrEnum):
    """Which layer of the two-layer model an expectation is about (PRD §7.1)."""

    L1 = "l1"
    """Code history on `time_varying` predicates: a change supersedes, never disputes."""

    L2 = "l2"
    """The `Fact.value` reconciliation slot: sources corroborate or contradict."""


class Outcome(StrEnum):
    """The labeled routing outcome of one expectation."""

    SUPERSEDE = "supersede"
    """L1: the code value changed; the old window closed, no review needed."""

    CONTRADICT = "contradict"
    """L2: at least two members of the slot disagree; flagged and routed to review."""

    CORROBORATE = "corroborate"
    """L2: the code projection and every doc claim agree; all kept, nothing merged."""

    ABSTAIN = "abstain"
    """L2: doc claim(s) exist but the projector cannot determine the code value.
    The claims stay *unverified* -- not drift (PRD §7.4, DRF-3, DRF-5)."""

    UNDOCUMENTED = "undocumented"
    """L2: no doc claim exists for this slot, so there is nothing to compare.
    Not drift (DRF-5); reported as a coverage metric."""


class DriftClass(StrEnum):
    """Classification of an open contradiction by its members' authors (DRF-4)."""

    DOC_VS_CODE = "doc_vs_code"
    DOC_VS_DOC = "doc_vs_doc"
    DOC_VS_DOC_VS_CODE = "doc_vs_doc_vs_code"


# The importer principals that author doc claims (PRD §7.6). `plumb-code` and
# `plumb-projector` author code facts and projections, never claims.
DOC_PRINCIPALS: frozenset[str] = frozenset(
    {"plumb-docstring", "plumb-readme", "plumb-docs", "plumb-changelog", "plumb-wiki"}
)


@dataclass(frozen=True, slots=True)
class Commit:
    """One commit in a scenario's history.

    Attributes:
        label: Short name unique within the scenario; expectations refer to it.
        message: The commit message.
        write: Files created or replaced, keyed by path relative to the
            scenario's root directory (POSIX separators).
        delete: Paths removed in this commit.
        tag: If set, a release tag `<scenario_id>/v<tag>` is created here
            (the PRD's `Release` entities come from tags, ING-9).
        broken: Python files in ``write`` that are *intentionally* not valid
            syntax (a half-typed edit). The linter checks they really fail to
            parse, and that every other Python file does.
    """

    label: str
    message: str
    write: Mapping[str, str] = field(default_factory=dict)
    delete: tuple[str, ...] = ()
    tag: str | None = None
    broken: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Expectation:
    """One labeled outcome, asserted after the named commit has been applied.

    Attributes:
        commit: Label of the commit after which the outcome is observed.
        symbol: Qualified symbol key, e.g. ``py:pkg.client.connect``.
        aspect: A concrete aspect from the catalog, e.g. ``param.timeout.default``.
        layer: Which layer the outcome is about.
        outcome: The expected routing outcome.
        code_value: The canonical code value the projector asserts after this
            commit, or ``None`` if it abstains.
        previous_code_value: L1 only -- the canonical value before this commit.
        claims: L2 only -- ``(importer principal, canonical value)`` for every
            active doc claim on the slot after this commit.
        drift_class: Required for ``CONTRADICT`` (DRF-4).
        introduced_in: For ``CONTRADICT``, the commit whose apply opened the
            contradiction (defaults to ``commit``); later commits that leave it
            open point back at the original.
        disposition: The resolution a reviewer is expected to choose (PRD §7.6).
            Documentation of intent for M2; M0/M1 tests do not resolve.
        note: Why this outcome is right, citing the PRD.
    """

    commit: str
    symbol: str
    aspect: str
    layer: Layer
    outcome: Outcome
    code_value: str | None = None
    previous_code_value: str | None = None
    claims: tuple[tuple[str, str], ...] = ()
    drift_class: DriftClass | None = None
    introduced_in: str | None = None
    disposition: Disposition | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class ClosureExpectation:
    """The expected ``namespace_closed`` value of a module or class after a commit (ADR-0003).

    ``closed=True`` means the importer must emit ``true``: every name in the
    namespace is determined by the source, so the projector may treat a missing
    name as absent. ``closed=False`` means it must emit ``false``: the projector
    abstains about missing names.
    """

    commit: str
    symbol: str
    closed: bool
    note: str = ""


@dataclass(frozen=True, slots=True)
class StateExpectation:
    """What the KB must say about a symbol's L1 state after a commit is ingested (ADR-0005).

    Unlike `Expectation` this is a statement about the *stored* state, so it can
    express removal (``present=False``) and, just as importantly, "left alone"
    (still ``present=True`` after a file stopped parsing).

    Attributes:
        commit: Label of the commit after which the state is observed.
        symbol: Symbol key, e.g. ``py:pkg.mod.f``.
        present: Expected ``Symbol.present``.
        kind: Expected ``Symbol.kind``, if it matters for the scenario.
        defined_at: Expected ``Symbol.defined_at`` relative to the scenario root.
        note: Why this is right.
    """

    commit: str
    symbol: str
    present: bool
    kind: str | None = None
    defined_at: str | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class ClaimsExpectation:
    """The doc claims the KB must hold as *present* on a fact after a commit (ADR-0006).

    Unlike an L2 `Expectation` this needs no module to exist at that commit, so it
    can say "the file was deleted, so its claims are gone", and no code projection,
    so it checks the claim protocol on its own. ``claims`` are
    ``(importer principal, canonical value)`` pairs; only the principals the
    pipeline actually has importers for are compared.
    """

    commit: str
    symbol: str
    aspect: str
    claims: tuple[tuple[str, str], ...]
    note: str = ""


@dataclass(frozen=True, slots=True)
class Scenario:
    """A seeded, labeled drift scenario.

    Attributes:
        id: A lowercase Python identifier; also the scenario's package name,
            its directory under ``scenarios/``, and the prefix of its symbol keys.
        title: One line describing the situation.
        prd_refs: PRD sections this scenario exercises, e.g. ``("§14#2",)``.
        commits: The history, oldest first.
        expectations: The labeled outcomes.
        closures: Expected ``namespace_closed`` values (ADR-0003).
        states: Expected stored L1 state, including removal (ADR-0005).
        claim_states: Expected present doc claims, including after deletion (ADR-0006).
    """

    id: str
    title: str
    prd_refs: tuple[str, ...]
    commits: tuple[Commit, ...]
    expectations: tuple[Expectation, ...]
    closures: tuple[ClosureExpectation, ...] = ()
    states: tuple[StateExpectation, ...] = ()
    claim_states: tuple[ClaimsExpectation, ...] = ()

    def commit_index(self, label: str) -> int:
        """Return the position of the commit named `label`.

        Raises:
            KeyError: No commit has this label.
        """
        for index, commit in enumerate(self.commits):
            if commit.label == label:
                return index
        raise KeyError(label)

    def files_at(self, label: str) -> dict[str, str]:
        """Return the scenario's file tree (relative path -> text) after commit `label`."""
        files: dict[str, str] = {}
        for commit in self.commits[: self.commit_index(label) + 1]:
            files.update(commit.write)
            for path in commit.delete:
                files.pop(path, None)
        return files
