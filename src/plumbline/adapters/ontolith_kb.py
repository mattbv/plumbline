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

from plumbline.adapters.ontolith_schema import build_schema
from plumbline.application.ports import RawClaim


class OntolithKnowledgeBase:
    """Wraps one Ontolith `Ontology` connection as Plumbline's `KnowledgeBase` port."""

    def __init__(self, kb: Ontology) -> None:
        self._kb = kb

    @classmethod
    def initialize(cls, path: Path, *, admin_principal_id: str) -> OntolithKnowledgeBase:
        """Create a fresh KB file, apply the Plumbline schema, and register the admin principal.

        This is what `plumb init` calls. Safe to call only against a path
        that doesn't exist yet -- `Ontology.connect()` creates the file, and
        re-running `apply_schema` for the same version is a no-op on the
        Ontolith side, but `plumb init` itself is meant for onboarding, not
        idempotent reconnection (see `plumbline.interfaces.cli`).
        """
        kb = Ontology.connect(path)
        kb.create_principal(
            admin_principal_id,
            kind="human",
            auth_method="oidc",
            default_capability="admin",
            trust_level=8,
        )
        kb.apply_schema(build_schema(), author=admin_principal_id)
        return cls(kb)

    def record_code_fact(self, symbol_key: str, field: str, value: str, *, as_of: datetime) -> None:
        """Write an L1 `Symbol.<field>` fact. Always supersedes (ADR-0001)."""
        raise NotImplementedError(
            "M1: needs plumb-code's own principal registered and Symbol.<field> "
            "resolved against the compiled schema -- see PRD §7.6/ADR-0001."
        )

    def record_claim(self, claim: RawClaim, *, author_principal: str, as_of: datetime) -> None:
        """Write an L2 `Fact.value` claim. Routes through Ontolith's static conflict handling."""
        raise NotImplementedError(
            "M1: needs the importer principal registered and the target Fact "
            "entity resolved/created by its natural key -- see PRD §7.2."
        )

    def close(self) -> None:
        self._kb.close()
