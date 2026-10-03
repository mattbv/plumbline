# ADR-0007: The Drift Projector: What It Projects, When It Abstains, and the Order It Runs In

## Status

Accepted

## Context

Drift appears when two authors state different values for the same `Fact.value`
slot (ADR-0001). The code side of L1 now exists (ADR-0003 to 0005), and so do
the doc claims (ADR-0006). What is missing is the author that states *the code's*
value in the same slot: the **drift projector**, a deterministic Reasoner that
turns L1 into `Fact.value` assertions. Without it no contradiction can ever open.
The PRD defines it in outline (§7.1, §7.4, DRF-2/3/7). Four points are left open
or turn out to be wrong, and I tested them against a real Ontolith KB.

### The order matters, and only one order works

PRD §7.7 orders a commit's application: retract projections, retract claims,
assert projections, assert claims. I applied one commit, in which the code default
changes from 30 to 60 *and* the README is fixed to 60 at the same time, in three
orders:

| Order | Result |
|---|---|
| **PRD:** retract projection, retract README claim, assert projection, assert README claim | Clean: projection 60 and README 60 both active, **0 open disputes** |
| Projection first, then docs: the projection is asserted while the README still says 30 | A **false contradiction** opens mid-commit (projection 60 vs README 30). The README importer then tries to retract its 30 and is **refused** (it is a party), so it can only add a third flagged member. The dispute stays open even though the commit fixed the docs |
| Docs first, then projection: README 60 is asserted while the projection still says 30 | The mirror failure: README 60 vs projection 30 flagged, and the projector's retraction of its 30 is **refused** |

Ontolith never lets a mistaken order be undone, because a claim in an open
dispute cannot be withdrawn by its author (ADR-0006). So the order is not style.
It is the difference between *no drift* and a permanent false positive that a
human must clear.

### Other findings

- The facts about a symbol can be found with `query("Fact").where(about=<symbol
  id>)`, and a fact's own claims with one `assertions(subject=…)` call, so the
  work per commit can be proportional to churn.
- A projection is just another author's claim: it has the same identity, the same
  retract-then-assert requirement, and the same refusal under dispute.
- **Gap in the importer.** `exists` and the signature facts are read from the `def`
  itself, but a decorator can change a callable's effective signature (a CLI
  command decorator, a wrapper that adds parameters). The importer currently
  emits signature facts regardless, so a projection built on them could assert a
  "parameter does not exist" that is false at runtime.
- **Gap in the blob (ADR-0004).** A missing `default` key means "the importer
  abstained", which cannot be told apart from "this parameter has no default". So
  the projector cannot say a documented default is wrong about a required
  parameter; it can only abstain.

## Decision (proposed)

### 1. Project exactly the slots that have a doc claim

A slot is projected iff it has at least one present doc claim after this commit's
claim step, and its projection is withdrawn when the last such claim leaves. This
reads DRF-2's "facts no doc mentions are not projected" at the level of the fact,
not the symbol. The knowledge base then grows with *documentation*, not with
code. The "undocumented" coverage view needs no stored projection: it is L1
minus the claims.

### 2. What the projection says, and when it abstains

A pure function (in the domain, with no I/O) from a symbol's L1 state and its
ancestors' to a value, or to **nothing**:

| Aspect | Projected value | Abstains when |
|---|---|---|
| `exists` | `true` if the symbol is present or `ambiguous`; `false` only if the symbol is removed or **was never seen**, and *every* enclosing module and class is present with `namespace_closed = true` | any enclosing namespace is open or unknown (ADR-0003) |
| `param.<p>.exists` | `true` if `p` is a named parameter; `false` if it is not **and** the signature has no `**kwargs` | the symbol is not a plain function or method, is `ambiguous`, or has no signature facts |
| `param.<p>.default`, `param.<p>.type`, `returns.type` | the value in `signature_json` | the key is absent (non-literal default, unannotated), per ADR-0004: never inferred |
| `raises.<Exc>` | `true` if the code raises it directly | otherwise, and it never projects `false` (R3) |
| `deprecated` | `is_deprecated` for functions, methods and classes | the symbol is not present or is `ambiguous` |

Every row also abstains when the symbol is unknown to L1 (an empty stub from a
doc claim), because unknown is not absent. Removed symbols project only `exists`.

### 3. The four-pass order is the contract

`IngestOneCommit` runs the commit in the PRD's order, with the projector as a
participant:

1. **L1** is written (done today).
2. **Plan, without writing:** the doc importers' wanted claims, the slots they
   touch, and the slots of every symbol whose L1 changed this commit that has a
   present claim (found through `Fact.about`).
3. **Retract projections** whose value changed or became undeterminable, or whose
   slot no longer has a claim.
4. **Retract doc claims** no longer stated (ADR-0006).
5. **Assert projections.**
6. **Assert doc claims.**

A retraction refused because the projection is under dispute is **deferred and
reported**, exactly like a doc claim (ADR-0006 §3): the projection stays at the
value the dispute is about, and the human sees that the code has since changed.

### 4. Authorship

A `plumb-projector` `service` principal with `write`, registered by `plumb init`
(PRD §7.6). Its claims are identified by `(fact, author, path, value)` like any
other, with the **path of the definition** (`Symbol.defined_at`) as the source
path, a SHA-pinned `#sym=` anchor, confidence 1.0, and a rationale such as
`projection of signature_json [drift-projector/1]`. The same set-difference
engine applies the doc claims and the projections.

### 5. Prerequisite: decorated callables abstain at the source

The importer emits no signature facts (no `param_names`, `param.*`, `returns.type`,
`raises`) for a function or method carrying a decorator outside a short
allow-list of those known to preserve the call signature: `staticmethod`,
`classmethod`, `abstractmethod`, `property` and its accessors, `final`,
`override`, `deprecated`, and the `functools` caching decorators. Its existence,
`kind`, and deprecation are still emitted. This tightens ADR-0003 in the same
conservative direction as Amendment 1.

### 6. Port changes

`KnowledgeBase` gains `facts_about(symbol_key)` (fact keys with a present claim)
and `claims_on(fact_key)` (every present claim, with its author), alongside the
existing `symbol_fields`.

### 7. How the zoo reads an outcome from the KB

This is what closes M0's exit criterion, so it is fixed here:

| Label | The KB shows |
|---|---|
| `corroborate` | at least one doc claim and a projection, all `active`, and no open contradiction on the fact |
| `contradict` | an open contradiction whose members are `flagged`; the drift class comes from the members' authors (DRF-4) |
| `abstain` | doc claim(s) present and **no** projection |
| `undocumented` | no doc claim, hence no projection |
| `supersede` (L1) | the `Symbol` field's window closed and linked (already checked) |

## Alternatives Considered

- **A. A participant in the commit protocol, slot-level, four passes (proposed).**
- **B. A separate pass after all claims are applied.** Simpler to build, but it is
  one of the two failing orders above: a transient false contradiction that the
  importers are then forbidden to clear.
- **C. Project every drift-capable aspect of any symbol with a claim (DRF-2 read
  at symbol level).** Gives a stored coverage picture at the price of a projection
  for every aspect nobody documented, which can never produce drift. Coverage is
  derivable without storing it.
- **D. Detect drift outside Ontolith by comparing claims to L1 at query time.**
  Contradicts DRF-1: drift is Ontolith's static routing, which is what gives it
  governance, provenance, a review queue, and resolution for free.
- **E. Make the doc importers refuse to assert anything that disagrees with L1.**
  Removes the very thing the product exists to find.

## Consequences

- Drift can finally appear: M0's exit criterion ("every seeded scenario's expected
  routing outcome is asserted") becomes executable for all 38 scenarios.
- New zoo scenarios, one per rule: code and docs fixed in the *same* commit (the
  experiment above, as a regression test); code changes and docs stale; a claim
  removed so its projection is withdrawn; dynamic module, `**kwargs`, `ambiguous`,
  decorated function, non-literal default; a never-seen symbol under closed and
  under open parents; a removed symbol; and a code change while the projection is
  disputed (deferred).
- `IngestReport` gains `projected`, `projections_withdrawn` and `abstained`. The last
  is the PRD's abstention-rate metric (§11).
- Per-commit cost stays proportional to churn: one relation lookup per changed
  symbol and one per-fact read per affected slot. The relation lookup scans, like
  ADR-0005's path lookup, and shares its fallback (a per-document index).
- Waivers (DRF-7) are M2: the projector will skip a value covered by an active
  `Waiver`; this ADR only reserves that hook.

## Open questions (resolved)

All five recommendations were accepted as written: slot-level projection; decorated callables
abstain at the source; `exists = false` for a symbol L1 has never seen when every enclosing
namespace is closed; a stuck projection is deferred and reported; and `deprecated = false`
is projected.

1. **Slot-level projection** (only slots that have a claim) rather than DRF-2's
   symbol-level reading. I recommend slot-level.
2. **Decorated callables abstain at the source** (§5). It costs some recall (a
   documented parameter on a decorated function is never checked) to avoid false
   "does not exist" findings. Agreed?
3. **`exists = false` for a symbol L1 has never seen**, when all its enclosing
   namespaces are closed. This is what flags "the README names a function that
   does not exist". I recommend it; the cost is only that it depends on the
   closure analysis being right.
4. **A stuck projection is deferred and reported**, like a doc claim.
5. **Projecting `deprecated = false`** when the code has no marker, so that
   "the docs say deprecated but the code is not" is drift. The code importer can
   only see static markers, so this is the least certain of the rows.

## Related, not decided here

`added_in` and `removed_in` come from the lineage Reasoner over release tags, and
`cli.*`, `env.*` and `project.*` from importers that do not exist yet. Each is a
separate producer of projections into the same slots, under its own principal, and
will reuse this ordering contract.

## Amendment 1: what implementing it showed

- **A dispute outlives its own premise, and that is by design.** If the README names a
  function the closed module never defined, the projector states `exists = false` and a
  dispute opens. If the module then gains a `__getattr__`, that projection is no longer
  provable, but the projector is a party to the dispute and Ontolith refuses its
  retraction. The projection is deferred and the dispute stays for a human, with the report
  saying the code has changed under it. This is the same "no auto-resolution" principle as
  PRD §7.6. The case where the projection is **not** in a dispute (a changelog that agrees
  the name is gone) is withdrawn and later restored cleanly. Both are zoo scenarios.
- **A namespace change must re-evaluate the facts beneath it.** Whether a child is provably
  absent depends on its parent's closure, so a change to a module or class re-plans every
  fact under it (`facts_under`), even though the children did not change. Without this, a
  module becoming dynamic would leave stale "does not exist" projections behind. This
  was found by a scenario, not foreseen.
- **A human resolution retracts the projection too.** Resolving a contradiction keeps one
  winner and retracts every other member, the projection included. The next commit that
  touches the file re-states it. If the docs and the code still disagree, a *new* dispute
  opens between exactly those two authors; the old one does not revive.
- **Verified against label-driven stand-ins for the unwritten importers.** Plumbline has a
  real code importer, a real docstring importer, and now the projector, but no README, docs
  or CHANGELOG importers. The zoo's 50 labeled L2 outcomes are checked through the whole
  pipeline, with `plumb-readme`, `plumb-docs` and `plumb-changelog` claims supplied by a
  test double that emits exactly what the labels say (`tests/zoo/standins.py`). That tests
  the projector, the pass order, and Ontolith's routing for real. Whether a future real
  importer extracts the same claims is that importer's own test, against the same labels.
- **Known limits, accepted.** A required parameter and a non-literal default are
  indistinguishable in `signature_json` (ADR-0004), so a documented default can only be
  checked where the code states one. A submodule the importer never analyzed (excluded,
  or unparseable) under a closed package would be projected absent.
