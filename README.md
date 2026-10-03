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

🚧 **Pre-Alpha.** What works today, checked end to end against a real Ontolith
knowledge base:

- `plumb ingest` replays a Git repository's history into a knowledge base, resumably
  and read-only: static analysis of Python source (symbols, signatures, deprecation,
  namespace closure), claims read from Python docstrings (Google, NumPy, Sphinx), and a
  drift projector that states *the code's* value in the same slot as each documented claim.
- `plumb drift` lists the resulting open contradictions, strongest first.

What does **not** exist yet: README, docs-page and CHANGELOG importers (so today it finds
docstring drift only), CLI/env/project facts, the review and resolution workflow, GitHub
integration, and `plumb explain` / `as-of` / `blame` / `check`. See the
[Implementation Plan](docs/Implementation_Plan.md), the
[full product spec](docs/PRD.md), and the [first run on a real repository](docs/first-real-run.md).

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

# Replay a repository's history into a knowledge base (the repository is only read)
uv run plumb ingest --repo /path/to/your/repo --kb /tmp/plumbline.db

# See what the docs and the code disagree about
uv run plumb drift --kb /tmp/plumbline.db
```

Or, to keep the configuration and knowledge base inside a project, run
`uv run plumb init --admin you@example.com` there first, then `plumb ingest` and `plumb drift`.

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
