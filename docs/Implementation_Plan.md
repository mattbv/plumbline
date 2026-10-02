# Plumbline — Implementation Plan

Live status tracker. The actual roadmap (scope, exit criteria, durations)
lives in [`docs/PRD.md`](PRD.md) §10 — this file just records where the
project actually is against that plan, updated as milestones close.

## Milestones

| Milestone | Scope | Exit criteria | Status |
|---|---|---|---|
| **M0 — Foundations** | Clean-architecture scaffold, tooling, CI, ADR-0001/0002, the drift zoo | Drift zoo ingestion is deterministic across two runs; every seeded scenario's routing outcome is asserted by tests | **Started.** Scaffold (this commit): package layout, `import-linter` contract, quality gates, `plumb init` real end to end against a real Ontolith KB. The drift zoo has its framework and a first 20 scenarios (`tests/zoo/`, ~60 more to go); the `CodeImporter` has its first part (symbols, signatures, raises, deprecation); the `DocImporter`s and the projector/lineage `Reasoner`s are not started. |
| **M1 — Drift Radar** (0.1) | Ingestion (ING-1–2, 4–11), drift detection (DRF-1–5, 7), read-only CLI | Drift-zoo precision ≥95%/recall ≥90%; ≥90% precision on a hand-labeled sample from 3 real repos | Not started |
| **M2 — Reconcile** (0.2) | Dispositions, waivers, GitHub App, MCP façade, backfill | Full J2→J3→merge→corroboration loop demonstrated on a real repo with a real agent; zero direct-write paths proven by a closed-set test | Not started |
| **M3 — Publish & Harden** (1.0) | Reference site, verified-context export, wiki ingestion, security review | All P0 requirements met; budgets green; no open high-severity security findings; 5 production design partners | Not started |

## Current focus

**M0.** The next concrete steps, in order:

1. The drift zoo: a synthetic Git repository with ~80 seeded, labeled
   scenarios (PRD §10 M0). Nothing in M1 can be trustworthy without it.
   *Framework and first 20 scenarios landed; see `tests/zoo/README.md` for
   what remains.*
2. A real `CodeImporter` (static AST analysis, PRD ING-1). *Part 1 landed
   (`plumbline.adapters.python_code_importer`): symbols, signatures,
   `raises`, and deprecation, checked against the drift zoo's labels. Part 2
   added the namespace-closure analysis (ADR-0003). The importer's output now
   assembles into L1 `Symbol` fields (ADR-0004, `plumbline.application.symbol_facts`).
   The write path is real (`IngestOneCommit` -> `OntolithKnowledgeBase`), and the
   zoo ingests deterministically into a real Ontolith KB. Still to do: `cli.*` (argparse/click/typer), `env.*`, and `project.*` facts, and
   the snapshot-vs-KB diff that derives "no longer exists".*
3. Widen `KnowledgeBase` (`plumbline.application.ports`) to expose what a real
   `Ontology` connection needs. *`symbol_fields` and `record_code_fact` landed
   (L1 writes, replay clock, out-of-order guard). `record_claim` (L2 doc claims:
   importer principals, `Fact` entity resolution by natural key) is still a
   deliberate `NotImplementedError` in `plumbline.adapters.ontolith_kb`. The
   snapshot-vs-KB diff that derives `present = false` is also still to do.*

## Notes for whoever picks this up

- Read [ADR-0001](adr/ADR-0001-two-layer-reconciliation-model.md) before
  touching `plumbline.adapters.ontolith_schema` or any use case that writes
  to the knowledge base. It's the one decision everything else follows from.
- The `import-linter` contract (`pyproject.toml`) is not a suggestion —
  `plumbline.domain` importing anything outside itself, or
  `plumbline.application` importing a concrete adapter, is a CI failure by
  design.
- `Ref["ConceptName"]` in the schema needs the literal quotes; see the
  module docstring in `plumbline.adapters.ontolith_schema` for exactly why
  (a real bug that shipped once, from `ruff --fix`, before `UP037` was
  disabled project-wide — don't re-enable it without reading that note).
