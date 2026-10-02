# ADR-0006: The Doc-Claim Model: Identity, the Apply Protocol, and Disputed Claims

## Status

Proposed

## Context

Drift appears only in L2. A documentation source states a value for a checkable
fact; the code's projection states one too; Ontolith's static routing on
`Fact.value` turns any difference into a contradiction (ADR-0001). The L1 side
now exists end to end. The doc side does not: `record_claim` is a stub, there
are no doc importers, and the PRD leaves several points open that determine how
the write path must work. I tested them against a real Ontolith KB with
per-source importer principals, because the PRD's descriptions turn out to be
only partly right.

What Ontolith actually does with competing `Fact.value` claims:

| Situation | Observed result |
|---|---|
| Two principals state the same value | Both stay `active` (corroboration); nothing merged |
| A third states a different value | **All three** become `flagged`; one contradiction opens |
| One principal changes its value (a README edit, 30 to 60) by asserting it | The principal **contradicts itself**: both its old and new claims are flagged |
| The same principal first retracts, then asserts | Clean: old is `retracted` with its window closed, new is `active` |
| A claim is retracted and the same value is later asserted again | Clean |
| The importer tries to retract its own claim that is a member of an open contradiction | **Raises `CapabilityError`** ("party to the contradiction; use `resolve_contradiction()`") |
| A non-party service principal tries the same retraction | Accepted, but **routed to human review** (not applied) |
| During an open dispute the importer asserts a new value | Accepted; it joins as a further flagged member (now with two of its own) |
| A human resolves, then the importer asserts the current value | Clean corroboration (the PRD's "re-affirm") |

Two consequences the PRD did not anticipate. First, **retract-then-assert is
mandatory, not stylistic** (the self-contradiction row). Second, PRD §7.7 says an
importer's retraction of a disputed claim "is routed to review rather than
applied"; that holds for a non-party but a *party* is refused outright, which is
exactly the importer's situation. An importer cannot withdraw its own stale claim
once it is disputed.

Also found: `Ontology.propose()` has no `metadata` parameter, although the
stored `Assertion` has a `metadata` field. The PRD's claim metadata
(`extractor_version`, `claim_fingerprint`, `section_id`, …) cannot be written
through the public API.

## Decision (proposed)

### 1. A claim is identified by `(fact, author, source path, value)`

- **fact**: the `Fact` natural key `<symbol_key>#<aspect>`.
- **author**: the per-source-kind importer principal (`plumb-readme`,
  `plumb-docs`, `plumb-docstring`, `plumb-changelog`; `plumb-wiki` later), each a
  `service` principal with `write`, created by `plumb init` (PRD §7.6).
- **source path**: from the claim's anchor.
- **value**: the canonical value (the importer canonicalizes before emitting).

A claim is *present* exactly when an active assertion with that identity exists.
Two values for one fact in one file are two claims (a document that contradicts
itself is real drift); the same value stated twice is one claim.

### 2. The apply protocol is a set difference per `(fact, author, path)`

For each changed source path, compare the claims the importer now extracts with
the active assertions authored by that principal from that path:

1. **Retract** claims no longer stated.
2. **Assert** claims newly stated.
3. **Do nothing** for unchanged claims. `valid_from` stays at the commit that
   first stated them, and the growth of the KB follows churn (PRD §7.7).

Retractions run before assertions, inside the same commit apply. A file that
disappears retracts everything its path authored. Files the importer did not
analyze are left alone, reusing ADR-0005's reasoning: never infer removal from
silence.

### 3. A disputed claim is deferred, not worked around

If the retraction is refused because the claim is a member of an open
contradiction, the importer **neither retracts nor asserts a replacement** for that
`(fact, author, path)`. It records the case as *deferred* in the ingest report.
The human resolving the dispute therefore sees the dispute as it stood, and the
report tells them the document has since changed (the PRD's own intent: "the
human resolving the dispute should see it").

After a human resolves the contradiction, a **re-affirm pass** re-reads the
current document and asserts whatever it now states (clean corroboration, see
the table). That pass is reconciliation work and belongs to M2; this ADR only
fixes the contract it will rely on.

### 4. Entities

- A `Fact` is created on its first claim, by the claiming principal, with its
  static `aspect` and its `about` relation.
- If the symbol the claim is about does not exist in L1, an empty `Symbol` entity
  is created so that `about` resolves. Such a symbol has no `present`, so the
  projector sees "unknown", never "absent". This is what lets a README that names
  a symbol that never existed be *recorded*, and later flagged by an `exists`
  projection where the namespace is closed (ADR-0003). `symbol_fields` returns an
  empty mapping for it, which the use case already treats as nothing known.
- `DocSource` and `DocSection` are not written yet; they exist for rendering and
  `as_of` of document text, not for drift.

### 5. Provenance without `metadata`

Until Ontolith lets `propose()` set `metadata`, the extraction rule and importer
version are carried in the assertion's `rationale` (for example
`md.table:config-defaults row 'timeout' [markdown-claim-importer/1]`). `source`
is the SHA-pinned anchor and `confidence` is extraction fidelity, as in the PRD.
A `claim_fingerprint` is not stored: the identity in §1 is derivable from the
assertion itself, so a suppression list can key on it. I would raise a
`metadata` parameter upstream.

### 6. Doc importers emit resolved claims or none

A `DocImporter` produces `RawClaim`s with a resolved `symbol_key`, or nothing. It
never guesses. A docstring knows its own symbol, so docstring claims resolve
trivially. Prose that says `connect` or `Client.connect` needs the module import
graph and re-exports (ING-6); that resolution is a **separate stage** with its own
decision, and unresolved or ambiguous references yield no claim and are counted.
Re-exports also need the import target recorded in L1 (an `alias_of` on import-bound
symbols), which ADR-0003 Amendment 1 deliberately did not record.

### 7. Port changes

`KnowledgeBase` gains `active_claims(author, path)` (the present claims, each with
its assertion id) and `retract_claim(id)`; `record_claim` keeps its shape and now
returns nothing it can fail silently on. A refused retraction surfaces as a typed
`ClaimDisputed` result, not an exception the use case must string-match.

## Alternatives Considered

- **A. Set difference per `(fact, author, path)` with retract-then-assert and
  deferral on dispute (proposed).**
- **B. Model claims as `time_varying` so an edit supersedes.** The PRD's central
  rule forbids it: stale docs would overwrite code truth (ADR-0001).
- **C. One principal per document.** Identity sprawl with no authentication
  behind it; the PRD chose one per source kind, and provenance already carries
  the path.
- **D. Assert the new value even during a dispute.** The importer ends up with
  two of its own members, the dispute grows with each edit, and a resolution can
  keep the stale one while retracting the current one, which the re-affirm pass
  would then re-open as a new dispute.
- **E. A privileged `plumb-reconciler` that retracts on the importers' behalf.**
  A non-party's retraction of a disputed claim still routes to human review, so
  nothing is gained, and it blurs who is accountable for a resolution (PRD §7.6).
- **F. Store a claim fingerprint in `metadata`.** Not possible through the public
  API today, and unnecessary given §1.

## Consequences

- Doc importers are pure and deterministic; the apply protocol lives in the
  application layer and is testable against fakes, then against a real KB.
- The zoo's L2 labels become executable once a doc importer and the projector
  exist: M0's exit criterion (every scenario's routing outcome asserted) closes.
  New zoo scenarios: an edit that changes a value; a claim removed from a file; a
  file deleted; the same value stated twice; two values in one file; an edit made
  while the claim is disputed (deferred); and a resolution followed by re-affirm.
- The ingest report grows a `deferred` list.
- PRD §7.7's note on disputed retractions is corrected: a party's retraction is
  refused, not routed. This ADR is where that correction is recorded.

## Open questions for you

1. **Deferral during a dispute** (neither retract nor assert), rather than
   asserting the new value anyway. I recommend deferral. The cost is that the
   dispute shows the old text until a human resolves it, which the report flags.
2. **The re-affirm pass belongs to M2.** M1 only records deferrals. Agreed?
3. **Empty `Symbol` entities for symbols L1 has never seen**, so claims about
   nonexistent symbols are recorded (and can later be flagged). The alternative,
   dropping such claims, silently loses "the README names something that does not
   exist", one of the most useful findings.
4. **Provenance in `rationale`** until `metadata` is available upstream.
5. **Resolution of prose references is a separate decision** (with an `alias_of`
   field for re-exports). OK to start with docstring and fully qualified
   references, where no resolver is needed?
