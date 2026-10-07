# Plumbline — Implementation Plan

Live status tracker. The actual roadmap (scope, exit criteria, durations)
lives in [`docs/PRD.md`](PRD.md) §10 — this file just records where the
project actually is against that plan, updated as work lands.

## Milestones

| Milestone | Exit criteria | Status |
|---|---|---|
| **M0 — Foundations** | Drift zoo ingestion is deterministic across two runs; every seeded scenario's routing outcome is asserted by tests | **Met, with one caveat.** Two ingestions of the zoo give byte-identical knowledge-base snapshots, and every labeled routing outcome is checked end to end against a real Ontolith KB. The caveat: README, docs and CHANGELOG claims come from label-driven stand-ins (`tests/zoo/standins.py`), because those importers do not exist yet. The zoo is still short of the PRD's ~80 scenarios. |
| **M1 — Drift Radar** (0.1) | Drift-zoo precision ≥95% / recall ≥90%; ≥90% precision on a hand-labeled sample from 3 real repos | **In progress; the real-code precision criterion is not met.** Done: code importer (ING-1), docstring importer (part of ING-2), the drift projector (DRF-1 to 4), `plumb ingest` and `plumb drift`, a Git reader, [a seeded-drift measurement](seeded-drift-evaluation.md), and a type comparison that abstains when it cannot prove a difference (ADR-0007 Amendments 3 and 4). That work took `rich` from 228 findings to 49 with none read as false, but it was tuned on `rich`: on [three further packages](precision-on-three-packages.md) I read 180 of 317 findings as false (57%), from four systematic causes. Those were fixed (317 down to 93 on the same packages), but on three packages the fixes had never seen I read 17 of 22 findings as false, from three new causes. Those were fixed in turn; on five packages chosen and baselined beforehand I read 44 of 184 findings as false (24%), from four further causes, and 79 more are narrower-docs findings that turn on a policy call. Those were decided and fixed in turn, and on a second set read once I read 7 of 67 findings as false (10%) and 42 as by-design (PRD §14 #10); the false rate has fallen on each set, and each set has still shown causes the earlier ones could not. Recall on provable injected drift is 100%, with more than half of the injected type drift withheld on purpose. Labels are one reader's. |
| **M2 — Reconcile** (0.2) | Full J2 → J3 → merge → corroboration loop on a real repo with a real agent; zero direct-write paths proven by a closed-set test | Not started. Deferral under dispute and the retract-then-assert protocol (ADR-0006, ADR-0007) are the groundwork. |
| **M3 — Publish & Harden** (1.0) | All P0 requirements met; budgets green; no open high-severity security findings; 5 production design partners | Not started |

## What exists

- **Code side (L1):** static analysis of Python source into `Symbol` facts — existence,
  signatures, defaults, types, raises, deprecation, namespace closure, ownership of symbol
  keys, and conservative removal (ADR-0003, 0004, 0005). Facts the importer stops stating are
  withdrawn rather than left stale (ADR-0004 Amendment 2).
- **Doc side (L2):** a claim write path with a set-difference apply protocol that defers
  anything stuck in a dispute (ADR-0006), and a docstring importer for Google, NumPy and
  Sphinx styles.
- **The projector:** states the code's value into each documented slot, in four ordered
  passes, abstaining unless it can prove the value (ADR-0007).
- **Interfaces:** `plumb init`, `plumb ingest` (resumable, read-only, with a report of what it
  left alone), `plumb drift`.

## Current focus

In order:

1. **Keep measuring on sets read once, and get a second reader.** The causes still open are a prose
   label read as an entry (`TODO:`), the word `optional` read as an entry, `0`/`1` defaults against
   `False`/`True`, and sentinels that are not `None` (`Undefined`). A second reader should mark
   [the sheet](second-reader-sheet.md); PRD §14 #10 is 63% of what remains and is the largest
   judgement call.
2. **README, docs-page and CHANGELOG importers**, with the symbol resolver they need
   (PRD ING-6, including an `alias_of` for re-exports). Until then only docstring drift is found.
3. **The remaining fact producers:** `cli.*`, `env.*` and `project.*` importers, and the lineage
   reasoner for `added_in` / `removed_in`.
4. **Toward M2:** the re-affirm pass after a resolution, waivers (DRF-7), and the remaining
   commands (`explain`, `as-of`, `blame`, `check`).

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
