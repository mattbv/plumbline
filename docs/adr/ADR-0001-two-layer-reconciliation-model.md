# ADR-0001: Two-Layer Reconciliation Model

## Status

Accepted

## Context

Plumbline's whole value proposition is using Ontolith's own conflict-routing
machinery to detect documentation drift, rather than building a separate
diffing engine (PRD §7.1). The obvious first design is: "a doc claim and the
corresponding code fact share one predicate." That design breaks
immediately, in both directions, because Ontolith routes conflicts **by a
predicate's declared temporality**, not by who authored the value or why:

- If the shared predicate is declared `time_varying`, a stale README
  re-import that disagrees with the current code would **supersede** the
  code's own, correct value. Staleness would silently overwrite truth —
  exactly the failure mode SPEC §10 (Ontolith's own conflict-handling
  specification) exists to prevent.
- If the shared predicate is declared `static`, every legitimate code
  change would **contradict** the previous code value. The review queue
  would fill with "the code changed" noise — the single fastest way to get
  a drift tool muted (PRD Risk R1/R9).

Neither choice works, and there is no third option within a single shared
predicate: Ontolith's routing is exactly two-valued (`static` →
contradiction-on-disagreement, `time_varying` → supersede-on-disagreement),
and there's no way to ask it to behave differently based on *who* is
writing.

## Decision

Two layers, one rule:

> Code history lives on `time_varying` predicates (`Symbol.*`).
> Reconciliation lives on `static`, single-valued predicates (`Fact.value`).
> Doc claims never touch a `time_varying` predicate.

- **L1 — Code facts** (`Symbol.signature_json`, `.present`, `.is_deprecated`,
  `.defined_at`): `time_varying`. Written only by the code importer. A code
  change supersedes the prior value — expected, no review.
- **L2 — Reconciliation slots** (`Fact.value`, one entity per
  `(symbol, aspect)`): `static`, `cardinality="single"`. Written by every
  doc importer *and* by a deterministic "drift projector" that mirrors the
  *current* L1 value into the matching L2 slot. Same value across sources →
  corroboration (Ontolith keeps all of them, confidence never merged).
  Different value → contradiction, flagged and routed to review.

Drift is then just Ontolith's own static routing firing on a projection and
a doc claim landing on the same slot with different values. No separate
comparison logic exists anywhere in Plumbline.

## Rationale

**Why not collapse L1 into L2's own projections, keeping one Symbol-level
slot per aspect?** Because keeping a projection current means *retracting*
the old one when the code changes, and Ontolith's `retracted` status means
"no longer asserted" — not "was true until time T." Collapsing the layers
would make `as_of(<past release>)` unable to reconstruct what the code
*actually was* at that point; only L1's own `time_varying` supersession
chain preserves that correctly (closed `valid_to` windows, not retractions).
L2 needs the opposite property: a resolved contradiction's losing members
should stay retracted, not reappear as "true at some past instant." Each
layer gets exactly the Ontolith semantics that fits what it's actually
recording.

**Why is this the load-bearing decision for the whole product, not an
implementation detail?** Every other architectural choice in Plumbline
follows from it: the schema (`docs/PRD.md` §7.5,
`plumbline.adapters.ontolith_schema`), the ingestion commit-apply protocol
(retract-then-assert on both layers, PRD §7.7), which Ontolith Reasoner
does what (the drift projector connects the layers; nothing else does), and
why a Validator *can't* be the thing that flags drift (a Validator only
rejects a write — it has no path to open a contradiction; drift here is
structural, emerging from routing itself, not from a plugin deciding to
flag something).

## Consequences

- Changing either layer's temporality is a breaking schema migration and
  needs its own ADR — see the module docstring warnings in
  `plumbline.adapters.ontolith_schema` at the exact lines this would touch.
- `Fact.value` equality comparison is now the *entire* precision mechanism.
  Every value that reaches it must already be canonicalized identically
  across sources (`plumbline.domain.canonical`) — a canonicalization gap is
  indistinguishable from real drift to Ontolith's routing.
- The drift projector must be conservative: it may only assert a projection
  it can prove, and must abstain (write nothing) otherwise (PRD §7.4). An
  incorrect projection is worse than a missing one — it fabricates
  contradictions against every doc source that happens to disagree with it.

## Alternatives Considered

- **One shared predicate, `time_varying`.** Rejected: lets stale docs
  overwrite the true code value (see Context).
- **One shared predicate, `static`.** Rejected: floods review with ordinary
  code evolution (see Context).
- **A separate, Plumbline-native diffing/comparison engine, bypassing
  Ontolith's conflict routing entirely.** Rejected: this is exactly the
  approach existing tools already take (PRD §2.3), and it forfeits
  Ontolith's provenance, bitemporal history, and governed-review machinery
  for free — the entire reason to build on Ontolith in the first place.

## References

- `docs/PRD.md` §7.1 (this decision's own full derivation), §7.5 (schema),
  §7.7 (ingestion protocol)
- Ontolith SPEC §10 (conflict semantics) and ADR-0017 (cardinality-aware
  routing, referenced by `DocSection.mentions`)
- `plumbline.adapters.ontolith_schema` (the schema this ADR governs)
