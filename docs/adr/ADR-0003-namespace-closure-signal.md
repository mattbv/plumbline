# ADR-0003: How the Projector Learns That Absence Is Provable

## Status

Proposed

## Context

The drift projector may project `exists = false` for a symbol, and
`param.<p>.exists = false` for a parameter, only when static analysis can
actually prove the thing is absent (PRD §7.4, DRF-3). It must **abstain** in
a module with `__getattr__`, with `*`-exports it cannot resolve, or with
dynamic registration; and when a signature has `**kwargs`. Abstaining is the
single most important precision lever (PRD §3 principle 3, §7.4).

The PRD says *that* the projector abstains, but not *how it knows to*. The
code importer (ADR-less, PRD ING-1) sees one snapshot of the changed files and
correctly asserts nothing about names it cannot see. But absence of a fact is
not evidence of absence, and the projector cannot tell "this module has no
`fancy`" from "this module resolves `fancy` at runtime". Two other constraints
shape the answer:

- **Replay.** Backfill replays history with a deterministic clock and must be
  reproducible (PRD §7.7, §9.4). Anything the projector depends on must live
  in the KB, versioned with the code, or `as_of(t)` and re-ingestion disagree.
- **Isolation.** Reasoners run sandboxed and read only flat `assertions()`,
  `get_entity()` and `schema()`; `query()` and `as_of()` are not available to
  them (PRD §7.8, Ontolith KI-101).

`**kwargs` needs no new signal: the importer already records it in
`param_names` (`"**options"`), so the projector can read it from L1 directly.
The open question is the *namespace* case: modules and classes whose member
names are not fully determined by the source text.

The dynamic cases are broader than `__getattr__`. A **class whose base is not
defined in the same file** is the likeliest source of false positives in real
repositories: `Client.connect` may be inherited from a base the importer was
never shown, so "not defined here" does not mean "does not exist".

## Decision (proposed)

Record, as an L1 fact, whether a module's or class's member namespace is
**closed**, and make the projector abstain unless it is.

- Add `Symbol.namespace_closed: Boolean`, `time_varying`, written only by the
  code importer, for symbols of kind `module` and `class`.
- **Default is to abstain.** The importer emits `true` only when every rule
  below holds; otherwise `false`. A symbol with no such fact (an old KB, an
  importer that did not run) is treated as not closed.
- The projector projects `exists = false` for a member only if its nearest
  enclosing module/class has `namespace_closed = true` **and** so does every
  ancestor. It projects `param.<p>.exists = false` only if `param_names`
  contains no `**` entry.

Starter rule set. A module is closed iff it has none of:

1. a module-level `__getattr__`;
2. any `from … import *` (conservative; relaxed only when the import graph
   from ING-6 can resolve the star, by amending this ADR);
3. writes to the module namespace at import time: `globals()[…] = …`,
   `vars()`, `setattr` on the module or `sys.modules[__name__]`,
   `exec`/`eval`.

A class is closed iff it has none of:

1. a `__getattr__` or `__getattribute__`;
2. a base class that is not `object` or another closed class **in the same
   file** (so inherited members are unresolved);
3. a `metaclass=` keyword, or a class decorator other than a short allow-list
   of decorators known not to add members.

Each rule is conservative on purpose. Adding a rule makes the projector
abstain more; removing one makes it assert more, so either is a change to
projected outcomes and goes through an amendment to this ADR.

## Alternatives Considered

- **A. `Symbol.namespace_closed` L1 field (proposed).** Versioned with the
  code, reproducible on replay, readable through flat `assertions()`, and
  consistent with how `present` and `is_deprecated` already work. Costs one
  schema version bump; Plumbline has no deployed KBs yet, so the migration
  cost is lowest now and grows later.
- **B. An internal entry in the aspect catalog.** Rejected: the catalog
  describes facets that *documentation* can state and that become `Fact`
  slots; "this namespace is closed" is something no doc claims and no slot
  can usefully dispute. It would blur drift-capable vs. internal aspects and
  force the `AspectCatalogValidator` to special-case it.
- **C. A side channel outside the KB (an analysis report the projector is
  handed).** Rejected: not versioned with the code, so backfill and `as_of(t)`
  could not reproduce a projection, and reasoners cannot read files anyway.
- **D. Project `exists = false` only for symbols previously seen present.**
  Cheapest, and it catches removals and renames (PRD §14 #5). Rejected as the
  *sole* mechanism: it still misfires when a symbol is deleted from a module
  that resolves it dynamically, and it gives up detecting documentation that
  names a symbol which never existed, a real and valuable finding in
  non-dynamic code. It remains a sensible *additional* guard.

## Consequences

- One `Symbol` schema version bump (`namespace_closed`), recorded in the
  schema history; schema versions are never deleted (PRD/Ontolith invariant).
- The code importer gains a closure analysis (pure AST, no I/O), with its own
  unit and property tests.
- The drift zoo gains scenarios, one per rule plus a closed-module positive
  control, and a way to label an expected `namespace_closed` value. The
  existing `dynamic_module_getattr` and `kwargs_abstention` scenarios stay valid.
- Recall drops for unusual-but-static code (a star import in an otherwise
  plain module). That is the intended trade: the PRD prefers missing drift to
  inventing it, and the coverage report already shows these as "unverified".
- Reports can show *why* a claim is unverified ("module has `__getattr__`")
  because the reason is recorded rather than inferred.

## Related, not decided here

The importer emits atomic per-aspect facts (`param.timeout.default`, …), but
L1 `Symbol` stores coarse fields (`signature_json`, `present`,
`is_deprecated`, `defined_at`), and `IngestOneCommit` currently passes the
aspect name straight through as the field name. How the importer's output is
mapped onto L1 fields (and how the projector turns L1 back into per-aspect
`Fact` slots) is a separate decision that needs its own ADR before
`KnowledgeBase.record_code_fact` is implemented. This ADR assumes only that
`namespace_closed` is one more `time_varying` `Symbol` field.
