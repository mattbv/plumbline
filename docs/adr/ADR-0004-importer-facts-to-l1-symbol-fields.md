# ADR-0004: How the Code Importer's Facts Become L1 `Symbol` Assertions

## Status

Accepted

## Context

The code importer (`PythonCodeImporter`) emits **atomic, per-aspect** facts:
`exists`, `param_names`, `param.timeout.default`, `param.timeout.type`,
`returns.type`, `raises.KeyError`, `deprecated`, `namespace_closed`, one
`RawClaim` each (PRD §7.4, ADR-0003).

The L1 schema stores a **handful of coarse `Symbol` fields**, all
`time_varying`: `defined_at`, `signature_json`, `is_deprecated`, `present`,
and now `namespace_closed` (PRD §7.5). The PRD's own worked examples assume
exactly this shape: §14 #1 has "`signature_json` **superseded**", §14 #5 has
"`Symbol(old_fn).present` superseded to `false`".

Nothing connects the two. Today `IngestOneCommit` passes each claim's *aspect
name* straight through as the `Symbol` *field name*
(`record_code_fact(symbol_key, claim.aspect, …)`), which names fields that do
not exist (`param.timeout.default`) and cannot express most of what the
importer found. `OntolithKnowledgeBase.record_code_fact` is a deliberate
`NotImplementedError` until this is decided.

Facts about Ontolith that constrain the answer (read from its write API):

- An assertion is **one value per `(entity, predicate)`**, written with
  `propose(subject, predicate, value, value_type, author, valid_from=…)`.
  Conflict routing comes from the predicate's declared temporality, never from
  the caller. A `time_varying` write supersedes the previous value and closes
  its window.
- Entities are created empty (`create_entity(concept, author, natural_key)`);
  every fact is then a separate assertion.
- Reasoners read through flat `assertions(subject, predicate)` calls
  (PRD §7.8, Ontolith KI-101): the projector must be able to reconstruct
  everything it needs from a symbol's current `time_varying` assertions.
- Importers diff against the KB's active state, so an unchanged value writes
  nothing (PRD §7.7). Whatever we store must therefore have a **canonical,
  deterministic serialization**, or equal values will look different and churn.

## Decision (proposed)

Keep the PRD's coarse `Symbol` fields and add a **pure assembly step** that
turns one commit's claims for a symbol into those fields. Nothing new in the
schema except what is called out under *Open questions*.

| Importer fact | L1 field | Value |
|---|---|---|
| `exists` = `true` | `present` | `true` |
| *(snapshot-vs-KB diff, not extracted)* | `present` | `false` (window closes) |
| `deprecated` | `is_deprecated` | `true`/`false` |
| `namespace_closed` | `namespace_closed` | `true`/`false` (modules, classes) |
| anchor of the `exists` claim | `defined_at` | the definition's **path** |
| `kind` (new importer fact, see below) | `kind` | `function`, `method`, `class`, `module`, `attribute`, and `ambiguous` for a name defined more than once (ADR-0005) |
| `param_names`, `param.<p>.exists/default/type`, `returns.type`, `raises.<Exc>` | `signature_json` | canonical JSON object (below) |

**`signature_json` v1** is one canonical JSON object: keys sorted, compact
separators, ASCII-safe, with a version key.

```json
{"params":{"timeout":{"default":"30","type":"None | int"}},"param_names":["host","timeout","**opts"],"raises":["KeyError"],"returns":"str","v":1}
```

- **A missing key means the importer abstained; it never means "none".** A
  non-literal default has no `"default"` entry, which is different from the
  literal default `"None"`. This keeps abstention (DRF-3) intact end to end.
- `raises` is a sorted list of exception names that were found; absence of a
  name proves nothing (PRD R3), so the list is corroboration-only data.
- Function/method symbols carry the blob; module/class symbols usually have
  none.

**`defined_at` stores the path, not the full anchor URI.** The anchor pins a
commit SHA, so storing it would supersede the field on every commit that
touches the file. The exact SHA and line span already live in each assertion's
`source` (its provenance), so the field only needs to say *where*, and it moves
only when the file does.

**The assembler** is a pure function in the application layer
(`claims → {field: canonical value}`), with the JSON canonicalizer in the
domain next to the other canonicalizers. `IngestOneCommit` groups a commit's
claims by symbol, assembles them, compares each field with the KB's active
value, and writes only the fields that changed.

**The projector** reads a symbol's `signature_json` with one flat
`assertions()` call and derives each aspect's code value from it (plus
`present`, `is_deprecated`, `namespace_closed`). It is the inverse of the
assembler, and the two are property-tested against each other.

## Alternatives Considered

- **A. Coarse fields plus a `signature_json` blob (proposed).** Matches the
  PRD's schema and worked examples, needs no new entity type, keeps a symbol's
  whole signature in one assertion so `as_of(t)` returns a coherent signature,
  and fits the projector's flat reads. **Cost:** history is coarser. Changing
  one default supersedes the whole blob, so "when did `timeout`'s default
  change?" is answered by diffing consecutive blob versions rather than by
  reading one assertion. That is mechanical and deterministic, and such reads
  are rare.
- **B. An L1 `CodeFact` entity per `(symbol, aspect)`**, mirroring the L2
  `Fact`. Gives exact per-aspect history and a one-to-one mapping to L2 slots.
  Rejected: it multiplies entities and assertions by the number of aspects
  (PRD §13 Q6 already worries about KB size), and it contradicts PRD §7.5 and
  ADR-0001, which define L1 as `Symbol.*`.
- **C. A `Parameter` concept per parameter** (default/type `time_varying`).
  Precise history for the part that changes most, with bounded entity growth.
  Rejected for now as extra schema and ordering machinery for a read pattern
  nobody has asked for; it can be introduced later by migrating the blob.
- **D. One `Symbol` field per aspect group** (`param_names`, `returns_type`,
  `raises_json`, `params_json`). Finer supersession, but `params_json` is still
  a blob, so most of the cost of A for little of its simplicity.

## Consequences

- The importer gains a `kind` fact (a machine-readable replacement for the
  current prose rationale), emitted like `namespace_closed`: an L1 fact that is
  not a catalog aspect.
- `IngestOneCommit` and the `KnowledgeBase` port change: grouping and diffing
  move into the use case, and the adapter needs an "ensure symbol entity"
  operation because entities are created empty. The `record_code_fact`
  `NotImplementedError` can finally be replaced.
- The drift zoo's L1 labels become checkable: each `SUPERSEDE` expectation
  can assert *which field* changed and that its canonical value is the labeled
  one, by running the importer through the assembler.
- Distinct importer outputs can collapse to one blob only if they are equal, so
  the canonical serialization is part of the contract and is versioned (`v`).
- Names bound by assignment or import (ADR-0003 Amendment 1) become `Symbol`s
  with `present = true` and no blob, so they need a `kind`.

## Open questions (resolved)

All three recommendations were accepted as written: `kind` is `time_varying`
(schema edited in place, which is still possible before the first release);
assigned and imported names get `kind = attribute`; and `raises` lives inside
`signature_json`.

1. **`kind` is `static` in the schema.** A name that changes from a function to
   a class would then open a *contradiction* on L1, which the model says must
   never happen for code history. I recommend making `kind` `time_varying`
   (still editable in place before the first release). Do you agree?
2. **`kind` for bound names.** I propose `attribute` for assigned and imported
   names and class/instance attributes, alongside the existing kinds. OK?
3. **`raises` inside `signature_json`.** The field's name says "signature" but
   it would also hold `raises`. I recommend keeping one blob and documenting
   the wider meaning over adding a fifth field. Acceptable?

## Related, not decided here

Deriving `present = false` needs the **snapshot-versus-KB diff**: a symbol
whose defining file changed in this commit but which the importer no longer
finds. It needs a way to ask the KB for the symbols defined in a given path,
and a rule for deleted files (which `read_file_at` cannot read). That is its
own small decision and follows this one.
