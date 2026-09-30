# ADR-0002: Application Ports Are `typing.Protocol`, Not an ABC Hierarchy

## Status

Accepted

## Context

The application layer (`plumbline.application.use_cases`) must depend on
abstractions for everything that touches the outside world — a real Git
repository, a real Ontolith connection, a real GitHub API — so a use case is
constructible and testable against a hand-written fake with zero real I/O
(PRD §9.4's determinism/testability principle, applied one layer up from
Ontolith's own `Clock`/`IdProvider` ports). Two ways to express "an
abstraction a use case depends on" are in common use in Python: an
`abc.ABC` base class every implementation must explicitly subclass, or a
`typing.Protocol` every implementation satisfies structurally, with no
inheritance relationship at all.

## Decision

Every port in `plumbline.application.ports` (`RepoReader`, `CodeImporter`,
`DocImporter`, `KnowledgeBase`, `ReviewSurface`) is a `typing.Protocol`.

## Rationale

- **Matches the substrate's own convention.** Ontolith's own ports
  (`StorageBackend`, `Embedder`, `AuthProvider`, `PolicyStrategy`) are
  Protocols, not an ABC hierarchy — a contributor moving between the two
  codebases sees one pattern, not two.
- **Test fakes need no inheritance and no `abc`-mandated boilerplate.**
  `tests/unit/application/test_ingest.py`'s `FakeRepoReader`/
  `FakeCodeImporter`/etc. are plain classes implementing the right methods
  — nothing imports `plumbline.application.ports` at all on the test-double
  side, which is exactly the decoupling a port is supposed to buy.
- **A real adapter can satisfy a port "by accident."** This is a feature,
  not a risk, here: it means a future adapter reusing an existing
  third-party client library's own class doesn't need a wrapper subclass
  purely to satisfy an ABC's inheritance requirement, as long as its method
  signatures match.

## Consequences

- Protocol conformance is a static-typing-time check (mypy `--strict`), not
  a runtime one. There is no `isinstance()` guarantee the way an ABC would
  give — acceptable here because every adapter is constructed explicitly by
  name in `plumbline.interfaces.cli` (or, from M2, a composition root), not
  discovered dynamically the way Ontolith's own `PluginRegistry` discovers
  third-party plugins by entry point. If Plumbline ever adds its own
  plugin-style dynamic discovery, that specific boundary should reconsider
  runtime validation (e.g. `@runtime_checkable`), not this ADR's own ports.
- A port's docstring is the only place its contract is written down beyond
  the type signature itself — keeping each one narrow (PRD's own review
  finding: don't expose more of `Ontology` than a use case actually needs)
  is what keeps this manageable without an ABC's more visible structure.

## Alternatives Considered

- **`abc.ABC` with `@abstractmethod`.** Rejected: no behavioral difference
  worth the inheritance boilerplate here, and it diverges from Ontolith's
  own established port style for no gain.
- **No formal port at all — use cases importing `ontolith.Ontology`
  directly.** Rejected outright: this is the one thing the `import-linter`
  contract in `pyproject.toml` exists to prevent (`plumbline.application`
  must not import `plumbline.adapters`), and it would make every use case
  test require a real Ontolith connection.

## References

- `plumbline.application.ports` (what this ADR governs)
- Ontolith's own `core/clock.py`, `store/base.py` (the `StorageBackend`
  port), `identity/ports.py` for the precedent this follows
