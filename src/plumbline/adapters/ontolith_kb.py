"""The real `KnowledgeBase` port implementation, backed by an Ontolith `Ontology`.

This is the one module in the whole package allowed to import `ontolith`'s
write-path API directly (`plumbline.adapters.ontolith_schema` is the other,
for the schema definitions themselves) -- everything above it in the
dependency direction (`application`, `domain`) talks to the `KnowledgeBase`
`Protocol` in `plumbline.application.ports`, never to `Ontology` itself.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ontolith import Ontology
from ontolith.core.ids import IdProvider

from plumbline.adapters.ontolith_schema import SCHEMA_NAMESPACE, build_schema
from plumbline.adapters.replay_clock import ReplayClock
from plumbline.application.ports import RawClaim

CODE_PRINCIPAL = "plumb-code"
"""The `service` principal that writes L1 code facts (PRD §7.6)."""


class OutOfOrderIngest(RuntimeError):
    """A write is older than the value it would supersede.

    Ingestion must be monotonic along the first-parent history (PRD §7.7).
    Applying an older commit on top of a newer state would silently move the
    KB backwards, so it is refused. This usually means a commit was delivered
    twice out of order, or a backfill was started on a non-empty KB.
    """


_BOOLEAN_FIELDS = frozenset({"present", "is_deprecated", "namespace_closed"})
_AUTO_ACCEPTED = "auto_accepted"


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
        """Write an L2 `Fact.value` claim. Routes through Ontolith's static conflict handling."""
        raise NotImplementedError(
            "M1: needs the importer principal registered and the target Fact "
            "entity resolved/created by its natural key -- see PRD §7.2."
        )

    def close(self) -> None:
        """Close the underlying Ontolith connection."""
        self._kb.close()
