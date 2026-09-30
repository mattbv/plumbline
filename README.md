# Plumbline

Governed, bitemporal reconciliation between a codebase and the documentation
that describes it. Built on [Ontolith](https://github.com/ontolith/ontolith).

Plumbline ingests a repository's source code and its documentation
(docstrings, README, `docs/`, CHANGELOG, GitHub wiki) into an Ontolith
knowledge base. Every documented statement that can be checked against code
becomes a provenanced assertion. Code changing over time is recorded as
supersession — expected, no review needed. Documentation disagreeing with
code, or with other documentation, becomes a flagged contradiction, routed
to a human. Nothing is silently overwritten; nothing is auto-resolved.

## Status

🚧 **Pre-Alpha.** This repository is an M0 foundations scaffold: the clean
architecture skeleton, tooling, and the `plumb init` command are real and
tested. Ingestion, drift detection, and reconciliation are M1 work — see the
[Implementation Plan](docs/Implementation_Plan.md) and the
[full product spec](docs/PRD.md).

## Why

See the [PRD](docs/PRD.md) for the full problem statement. In short: code
changes are enforced (tests fail); doc changes aren't. The same fact lives
in many places (a signature, its docstring, a README table, a changelog
entry), and a PR updates one or two of them. Drift is invisible until it
costs something. Plumbline makes documentation drift a first-class,
governed, auditable thing — using Ontolith's own conflict-routing and
provenance model as the actual mechanism, not a bolted-on diff tool.

## Quick start

```bash
# Clone
git clone https://github.com/mattbv/plumbline.git
cd plumbline

# Install (requires Python >=3.11 and uv: https://github.com/astral-sh/uv)
uv sync --all-extras

# Run the test suite
uv run pytest

# Initialize a knowledge base in the current directory
uv run plumb init --admin you@example.com
```

## Architecture

Plumbline follows the same ports-and-adapters (hexagonal) architecture
Ontolith itself uses, enforced by an `import-linter` contract:

```
src/plumbline/
├── domain/        # Pure logic: the aspect catalog, canonicalization,
│                   # anchor URIs, dispositions. No I/O, no Ontolith import.
├── application/    # Use cases, depending only on abstract ports.
│   ├── ports.py     # RepoReader, CodeImporter, DocImporter, KnowledgeBase,
│   │                 # ReviewSurface — Protocols, not concrete classes.
│   └── use_cases/
├── adapters/       # Concrete implementations: the real Ontolith-backed
│                    # knowledge base, the schema, Git access, extractors.
└── interfaces/
    └── cli.py       # `plumb` — the CLI entrypoint.
```

The core modeling decision (see
[ADR-0001](docs/adr/ADR-0001-two-layer-reconciliation-model.md)): code
history lives on `time_varying` Ontolith properties; reconciliation lives on
one `static` slot per checkable fact. Drift detection is Ontolith's own
static conflict routing — there is no separate diffing engine.

## Documentation

- [Product Requirements Document](docs/PRD.md)
- [Implementation Plan](docs/Implementation_Plan.md)
- [Architecture Decision Records](docs/adr/)
- [Contributing](CONTRIBUTING.md)

## License

Apache-2.0 — see [LICENSE](LICENSE).
