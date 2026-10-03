"""The real `KnowledgeBase` port implementation, backed by an Ontolith `Ontology`.

This is the one module in the whole package allowed to import `ontolith`'s
write-path API directly (`plumbline.adapters.ontolith_schema` is the other,
for the schema definitions themselves) -- everything above it in the
dependency direction (`application`, `domain`) talks to the `KnowledgeBase`
`Protocol` in `plumbline.application.ports`, never to `Ontology` itself.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from pathlib import Path

from ontolith import Ontology
from ontolith.core.entity import Entity
from ontolith.core.errors import CapabilityError
from ontolith.core.ids import IdProvider

from plumbline.adapters.ontolith_schema import SCHEMA_NAMESPACE, build_schema
from plumbline.adapters.replay_clock import ReplayClock
from plumbline.application.drift import DriftClaim, DriftItem, classify
from plumbline.application.ports import ActiveClaim, PresentClaim, RawClaim, RetractOutcome
from plumbline.application.projection import PROJECTOR_PRINCIPAL
from plumbline.domain import anchors

CODE_PRINCIPAL = "plumb-code"
"""The `service` principal that writes L1 code facts (PRD §7.6)."""


class OutOfOrderIngest(RuntimeError):
    """A write is older than the value it would supersede.

    Ingestion must be monotonic along the first-parent history (PRD §7.7).
    Applying an older commit on top of a newer state would silently move the
    KB backwards, so it is refused. This usually means a commit was delivered
    twice out of order, or a backfill was started on a non-empty KB.
    """


DOC_PRINCIPALS = ("plumb-changelog", "plumb-docs", "plumb-docstring", "plumb-readme")
"""One `service` principal per documentation source kind (PRD §7.6): provenance can
then answer which *kind* of source is stale, and a whole kind can be distrusted."""

_PRESENT_CLAIM_STATES = frozenset({"active", "flagged"})

_BOOLEAN_FIELDS = frozenset({"present", "is_deprecated", "namespace_closed"})
_AUTO_ACCEPTED = "auto_accepted"


def _path_of(source: str | None) -> str:
    """The path in an assertion's anchor, or empty if it has none."""
    try:
        return anchors.parse(source).path if source else ""
    except ValueError:
        return ""


def _require_auto_accepted(proposal: object, author: str, subject: str) -> None:
    """Raise unless an importer principal's write landed without review."""
    state = str(
        getattr(getattr(proposal, "state", None), "value", getattr(proposal, "state", None))
    )
    if state != _AUTO_ACCEPTED:
        raise RuntimeError(f"{author} write for {subject} was {state}, not auto-accepted")


class OntolithKnowledgeBase:
    """Wraps one Ontolith `Ontology` connection as Plumbline's `KnowledgeBase` port.

    Args:
        kb: A connected `Ontology` whose clock is ``clock``.
        clock: The `ReplayClock` the ``Ontology`` was connected with.
        replay: Backfill mode (PRD §7.7): pin each write's ``asserted_at`` to
            its commit time. Live mode leaves the clock on real time.
    """

    def __init__(self, kb: Ontology, clock: ReplayClock, *, replay: bool = False) -> None:
        self._kb = kb
        self._clock = clock
        self._replay = replay

    @classmethod
    def initialize(
        cls,
        path: Path,
        *,
        admin_principal_id: str,
        replay: bool = False,
        id_provider: IdProvider | None = None,
    ) -> OntolithKnowledgeBase:
        """Create a fresh KB file, apply the Plumbline schema, and register the principals.

        This is what `plumb init` calls. Safe to call only against a path
        that doesn't exist yet -- `Ontology.connect()` creates the file, and
        re-running `apply_schema` for the same version is a no-op on the
        Ontolith side, but `plumb init` itself is meant for onboarding, not
        idempotent reconnection (see `plumbline.interfaces.cli`).

        Args:
            path: Where to create the KB file.
            admin_principal_id: The human admin to register.
            replay: Backfill mode, see the class docs.
            id_provider: Override Ontolith's ID source (a deterministic one makes
                two backfills of the same history byte-identical).
        """
        clock = ReplayClock()
        kb = Ontology.connect(path, clock=clock, id_provider=id_provider)
        kb.create_principal(
            admin_principal_id,
            kind="human",
            auth_method="oidc",
            default_capability="admin",
            trust_level=8,
        )
        kb.apply_schema(build_schema(), author=admin_principal_id)
        kb.create_principal(
            CODE_PRINCIPAL,
            kind="service",
            auth_method="workload",
            default_capability="write",
            author=admin_principal_id,
        )
        for principal in (*DOC_PRINCIPALS, PROJECTOR_PRINCIPAL):
            kb.create_principal(
                principal,
                kind="service",
                auth_method="workload",
                default_capability="write",
                author=admin_principal_id,
            )
        return cls(kb, clock, replay=replay)

    @classmethod
    def open(
        cls, path: Path, *, replay: bool = False, id_provider: IdProvider | None = None
    ) -> OntolithKnowledgeBase:
        """Connect to an existing KB created by `initialize`."""
        clock = ReplayClock()
        return cls(
            Ontology.connect(path, clock=clock, id_provider=id_provider), clock, replay=replay
        )

    def is_empty(self) -> bool:
        """Whether no symbol has ever been written (a fresh KB, safe to backfill into)."""
        return int(self._kb.query("Symbol").count()) == 0

    def open_drift(self) -> list[DriftItem]:
        """Every open contradiction as a finding, strongest first (PRD J1, step 3)."""
        o = self._kb
        items: list[DriftItem] = []
        for dispute in o.contradictions():
            if str(getattr(dispute.state, "value", dispute.state)) != "open":
                continue
            fact = o.get_entity(dispute.subject)
            if fact is None or fact.natural_key is None:
                continue
            members = set(dispute.member_ids)
            claims = tuple(
                DriftClaim(
                    a.author, str(a.value), _path_of(a.source), a.source or "", a.confidence or 0.0
                )
                for a in o.assertions(subject=dispute.subject, predicate="Fact.value", status=None)
                if a.id in members
            )
            items.append(DriftItem(fact.natural_key, classify(claims), dispute.created_at, claims))
        return sorted(items, key=lambda i: (-i.score, i.fact_key))

    def symbol_fields(self, symbol_key: str) -> dict[str, str] | None:
        """Active L1 values for a symbol keyed by `Symbol` field name, or ``None`` if unknown."""
        entity = self._kb.backend.get_entity_by_natural_key(SCHEMA_NAMESPACE, "Symbol", symbol_key)
        if entity is None:
            return None
        return {
            a.predicate.removeprefix("Symbol."): str(a.value)
            for a in self._kb.assertions(subject=entity.id)
            if a.predicate.startswith("Symbol.") and a.valid_to is None
        }

    def withdraw_code_fact(self, symbol_key: str, field: str, *, as_of: datetime) -> None:
        """Retract the active `Symbol.<field>` assertion, so the field reads as not stated."""
        entity = self._kb.backend.get_entity_by_natural_key(SCHEMA_NAMESPACE, "Symbol", symbol_key)
        if entity is None:
            return
        if self._replay:
            self._clock.pin(as_of)
        for assertion in self._kb.assertions(subject=entity.id, predicate=f"Symbol.{field}"):
            if assertion.valid_to is None:
                proposal, _decision = self._kb.retract(assertion.id, CODE_PRINCIPAL)
                _require_auto_accepted(proposal, CODE_PRINCIPAL, f"{symbol_key} {field}")

    def symbols_defined_in(self, path: str) -> list[str]:
        """Keys of present symbols whose active `defined_at` is `path`, sorted.

        Uses Ontolith's query on a literal property. That is not indexed, so it
        scans: measured ~3 ms per path at 6k symbols and ~30 ms at 30k (ADR-0005
        keeps a per-file manifest as the fallback if this ever dominates).
        """
        keys = []
        for entity in self._kb.query("Symbol").where(defined_at=path).all():
            present = [
                a
                for a in self._kb.assertions(subject=entity.id, predicate="Symbol.present")
                if a.valid_to is None
            ]
            if present and str(present[0].value) == "true" and entity.natural_key is not None:
                keys.append(entity.natural_key)
        return sorted(keys)

    def record_code_fact(
        self, symbol_key: str, field: str, value: str, *, as_of: datetime, source: str
    ) -> None:
        """Write one `Symbol.<field>` fact; a changed value supersedes the old one (ADR-0001).

        Raises:
            OutOfOrderIngest: ``as_of`` is earlier than the value being superseded.
            RuntimeError: The write was not auto-accepted, i.e. `plumb-code` is
                missing the `write` capability -- a configuration error, since
                importing what the code says is observation, not editorializing.
        """
        entity = self._kb.backend.get_entity_by_natural_key(SCHEMA_NAMESPACE, "Symbol", symbol_key)
        if entity is None:
            entity = self._kb.create_entity("Symbol", CODE_PRINCIPAL, natural_key=symbol_key)
        predicate = f"Symbol.{field}"
        opened = [
            a.valid_from
            for a in self._kb.assertions(subject=entity.id, predicate=predicate)
            if a.valid_from is not None
        ]
        newest = max(opened, default=None)
        if newest is not None and as_of < newest:
            raise OutOfOrderIngest(
                f"{symbol_key} {field}: commit time {as_of.isoformat()} is before the "
                f"current value's {newest.isoformat()}"
            )
        if self._replay:
            self._clock.pin(as_of)
        proposal, _decision = self._kb.propose(
            entity.id,
            predicate,
            value,
            "Boolean" if field in _BOOLEAN_FIELDS else "Text",
            CODE_PRINCIPAL,
            confidence=1.0,
            source=source,
            rationale=f"code importer: {field}",
            valid_from=as_of,
        )
        state = str(getattr(proposal.state, "value", proposal.state))
        if state != _AUTO_ACCEPTED:
            raise RuntimeError(
                f"{CODE_PRINCIPAL} write for {symbol_key} {field} was {state}, not auto-accepted"
            )

    def record_claim(self, claim: RawClaim, *, author_principal: str, as_of: datetime) -> None:
        """Write an L2 `Fact.value` claim; static single routing decides corroborate or contradict.

        Creates the `Fact` on first use -- with its static ``aspect`` and its
        ``about`` relation -- and an empty `Symbol` when L1 has never seen the
        symbol, so a claim about something that does not exist is still recorded
        (ADR-0006 §4).

        Raises:
            RuntimeError: The write was not auto-accepted (a misconfigured importer
                principal), mirroring `record_code_fact`.
        """
        if self._replay:
            self._clock.pin(as_of)
        fact = self._kb.backend.get_entity_by_natural_key(SCHEMA_NAMESPACE, "Fact", claim.fact_key)
        if fact is None:
            fact = self._create_fact(claim, author_principal, as_of)
        proposal, _decision = self._kb.propose(
            fact.id,
            "Fact.value",
            claim.raw_value,
            "Text",
            author_principal,
            confidence=claim.confidence,
            source=claim.anchor_uri,
            rationale=claim.rationale,
            valid_from=as_of,
        )
        _require_auto_accepted(proposal, author_principal, claim.fact_key)

    def _create_fact(self, claim: RawClaim, author: str, as_of: datetime) -> Entity:
        """Create a ``Fact`` with its static aspect and its ``about`` link to the symbol."""
        symbol = self._kb.backend.get_entity_by_natural_key(
            SCHEMA_NAMESPACE, "Symbol", claim.symbol_key
        )
        if symbol is None:
            symbol = self._kb.create_entity("Symbol", author, natural_key=claim.symbol_key)
        fact = self._kb.create_entity("Fact", author, natural_key=claim.fact_key)
        for proposal, _ in (
            self._kb.propose(
                fact.id,
                "Fact.aspect",
                claim.aspect,
                "Text",
                author,
                source=claim.anchor_uri,
                valid_from=as_of,
            ),
            self._kb.propose_ref(
                fact.id, "Fact.about", symbol.id, author, source=claim.anchor_uri, valid_from=as_of
            ),
        ):
            _require_auto_accepted(proposal, author, claim.fact_key)
        return fact

    def active_claims(
        self, author_principal: str, paths: Collection[str]
    ) -> dict[str, list[ActiveClaim]]:
        """Present claims by ``author_principal`` from each path, in a single KB scan.

        "Present" means active, or flagged because it is a member of an open
        contradiction. Ontolith cannot filter by author or source, so this reads
        every `Fact.value` assertion once (~11 µs each, ~0.3 s at 30k claims); a
        per-document index is the fallback if that ever dominates (ADR-0006).
        """
        wanted = set(paths)
        found: dict[str, list[ActiveClaim]] = {path: [] for path in wanted}
        for a in self._kb.assertions(predicate="Fact.value", status=None):
            if (
                a.author != author_principal
                or a.valid_to is not None
                or str(getattr(a.status, "value", a.status)) not in _PRESENT_CLAIM_STATES
                or a.source is None
            ):
                continue
            try:
                path = anchors.parse(a.source).path
            except ValueError:
                continue
            if path not in wanted:
                continue
            fact = self._kb.get_entity(a.subject)
            if fact is not None and fact.natural_key is not None:
                found[path].append(ActiveClaim(a.id, fact.natural_key, str(a.value), path))
        return found

    def facts_about(self, symbol_key: str) -> list[str]:
        """Keys of the facts whose ``about`` is this symbol, sorted."""
        symbol = self._kb.backend.get_entity_by_natural_key(SCHEMA_NAMESPACE, "Symbol", symbol_key)
        if symbol is None:
            return []
        return sorted(
            fact.natural_key
            for fact in self._kb.query("Fact").where(about=symbol.id).all()
            if fact.natural_key is not None
        )

    def fact_keys(self) -> list[str]:
        """Keys of every fact in the KB, sorted (a full scan: for tools and measurements)."""
        return sorted(
            fact.natural_key
            for fact in self._kb.query("Fact").all()
            if fact.natural_key is not None
        )

    def facts_under(self, symbol_key: str) -> list[str]:
        """Keys of the facts about this symbol's descendants (``py:a.b`` covers ``py:a.b.f``).

        Scans every `Fact`, because the key prefix is not indexed. It is called only when
        a *namespace* symbol changed, which is rare.
        """
        prefix = f"{symbol_key}."
        return sorted(
            fact.natural_key
            for fact in self._kb.query("Fact").all()
            if fact.natural_key is not None and fact.natural_key.startswith(prefix)
        )

    def claims_on(self, fact_key: str) -> list[PresentClaim]:
        """Every present claim on a fact (active, or flagged in an open dispute)."""
        fact = self._kb.backend.get_entity_by_natural_key(SCHEMA_NAMESPACE, "Fact", fact_key)
        if fact is None:
            return []
        found: list[PresentClaim] = []
        for a in self._kb.assertions(subject=fact.id, predicate="Fact.value", status=None):
            if (
                a.valid_to is not None
                or a.source is None
                or str(getattr(a.status, "value", a.status)) not in _PRESENT_CLAIM_STATES
            ):
                continue
            try:
                path = anchors.parse(a.source).path
            except ValueError:
                continue
            found.append(PresentClaim(a.id, a.author, str(a.value), path))
        return sorted(found, key=lambda c: (c.author, c.path, c.value))

    def retract_claim(
        self, claim_id: str, *, author_principal: str, as_of: datetime
    ) -> RetractOutcome:
        """Withdraw a claim, unless it is a member of an open contradiction.

        Ontolith refuses a *party* to a contradiction (the claim's own author) with
        a `CapabilityError`, and would route anyone else to human review. Either
        way the claim is still in force, which is `DISPUTED` (ADR-0006 §3).
        """
        if self._replay:
            self._clock.pin(as_of)
        try:
            proposal, _decision = self._kb.retract(claim_id, author_principal)
        except CapabilityError:
            return RetractOutcome.DISPUTED
        state = str(getattr(proposal.state, "value", proposal.state))
        return RetractOutcome.RETRACTED if state == _AUTO_ACCEPTED else RetractOutcome.DISPUTED

    def close(self) -> None:
        """Close the underlying Ontolith connection."""
        self._kb.close()
