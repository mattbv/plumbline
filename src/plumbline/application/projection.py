"""Planning the drift projector's writes (ADR-0007).

The projector is the author that states *the code's* value in a ``Fact.value`` slot, so
that a doc claim that disagrees becomes an Ontolith contradiction. This module only
*plans*: for the facts a commit may have affected it works out which projections to
withdraw and which to assert. The use case applies the plan in the order the protocol
requires; the value rules live, pure, in `plumbline.domain.projection`.

A projection is wanted exactly when its slot has a doc claim after this commit, so the
knowledge base grows with the documentation, not with the code. It is withdrawn when the
last claim leaves.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from plumbline.application.ports import CommitRef, KnowledgeBase, PresentClaim, RawClaim
from plumbline.domain import anchors
from plumbline.domain.anchors import Anchor
from plumbline.domain.projection import SymbolState, is_projectable, project

PROJECTOR_PRINCIPAL = "plumb-projector"
"""The `service` principal that authors projections (PRD §7.6)."""

_VERSION = "drift-projector/1"
_FIELD_FOR = {"exists": "present", "deprecated": "is_deprecated"}


@dataclass(frozen=True, slots=True)
class DocChanges:
    """How this commit is about to change the doc claims, before it is applied.

    Attributes:
        retracting: Ids of the doc claims about to be withdrawn.
        asserting: For each fact key, how many new doc claims are about to be written.
    """

    retracting: frozenset[str]
    asserting: dict[str, int]

    @property
    def touched_facts(self) -> set[str]:
        """Facts whose doc claims change, so whose projection may need to appear or go."""
        return set(self.asserting)


@dataclass(frozen=True, slots=True)
class ProjectionStep:
    """What to do about one fact's projection."""

    fact_key: str
    retract: list[PresentClaim]
    assert_: list[RawClaim]


@dataclass(frozen=True, slots=True)
class ProjectionPlan:
    """The projector's decisions for one commit.

    Attributes:
        steps: Facts whose projection must change.
        abstained: Documented slots in the affected set for which the code's value could
            not be proven (the PRD's abstention-rate numerator).
    """

    steps: list[ProjectionStep]
    abstained: int = 0


class Projector:
    """Plans projections from L1 state; performs no writes."""

    def __init__(self, kb: KnowledgeBase, owner: str, repo: str) -> None:
        self._kb = kb
        self._owner = owner
        self._repo = repo

    def plan(
        self, commit: CommitRef, fact_keys: Collection[str], changes: DocChanges
    ) -> ProjectionPlan:
        """Decide, for each affected fact, which projections to withdraw and assert."""
        cache: dict[str, SymbolState] = {}
        steps: list[ProjectionStep] = []
        abstained = 0
        for fact_key in sorted(fact_keys):
            symbol_key, _, aspect = fact_key.partition("#")
            if not is_projectable(aspect):
                continue
            present = self._kb.claims_on(fact_key)
            documented = sum(
                1
                for c in present
                if c.author != PROJECTOR_PRINCIPAL and c.claim_id not in changes.retracting
            ) + changes.asserting.get(fact_key, 0)
            wanted: dict[tuple[str, str], RawClaim] = {}
            if documented:
                claim = self._projection(commit, symbol_key, aspect, cache)
                if claim is None:
                    abstained += 1
                else:
                    wanted[(claim.raw_value, anchors.parse(claim.anchor_uri).path)] = claim
            have = {(c.value, c.path): c for c in present if c.author == PROJECTOR_PRINCIPAL}
            retract = [c for key, c in sorted(have.items()) if key not in wanted]
            assert_ = [c for key, c in sorted(wanted.items()) if key not in have]
            if retract or assert_:
                steps.append(ProjectionStep(fact_key, retract, assert_))
        return ProjectionPlan(steps, abstained)

    def _projection(
        self, commit: CommitRef, symbol_key: str, aspect: str, cache: dict[str, SymbolState]
    ) -> RawClaim | None:
        """The claim stating the code's value for one slot, or ``None`` if it cannot be proven."""
        state = self._state(symbol_key, cache)
        chain = self._ancestors(symbol_key, cache)
        value = project(aspect, state, chain)
        path = state.defined_at or next((a.defined_at for a in chain if a.defined_at), None)
        if value is None or path is None:
            return None
        anchor = Anchor(
            "repo",
            self._owner,
            self._repo,
            commit.sha,
            path,
            symbol=symbol_key.removeprefix("py:"),
        )
        field = _FIELD_FOR.get(aspect, "signature_json")
        return RawClaim(
            symbol_key, aspect, value, anchor.to_uri(), 1.0, f"projection of {field} [{_VERSION}]"
        )

    def _state(self, symbol_key: str, cache: dict[str, SymbolState]) -> SymbolState:
        """A symbol's L1 state, read once per commit."""
        if symbol_key not in cache:
            cache[symbol_key] = SymbolState.from_fields(self._kb.symbol_fields(symbol_key))
        return cache[symbol_key]

    def _ancestors(self, symbol_key: str, cache: dict[str, SymbolState]) -> list[SymbolState]:
        """Enclosing namespaces, nearest first, up to and including the first module.

        Stops early at a symbol the KB has never seen: past it the chain is unknown, and
        the rules treat a chain that does not end in a module as "not provable".
        """
        chain: list[SymbolState] = []
        parent = symbol_key
        while "." in parent:
            parent = parent.rpartition(".")[0]
            state = self._state(parent, cache)
            chain.append(state)
            if state.kind in ("module", None):
                break
        return chain
