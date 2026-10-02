# ADR-0005: Detecting Removed Symbols, and Who Owns a Symbol Key

## Status

Accepted

## Context

Ingestion now writes L1 `Symbol` facts for what the importer finds (ADR-0004),
but **nothing ever writes `present = false`**. When a commit deletes a function,
renames a class, or removes a whole file, the importer simply finds nothing, so
the KB keeps the stale `present = true` forever. Documentation that still names
the deleted symbol is then never flagged: PRD §14 #5 (rename) and §7.4's
`exists` drift cannot work. The use case's own comment marks this as the next
step.

Detecting removal is a *difference* (what the KB believed was defined in a file
versus what the file defines now), so it needs the KB to say which symbols a
file defined. Researching that turned up four facts that shape the design.

**1. Asking the KB "which symbols does this file define" works, but is a scan.**
`Ontology.query("Symbol").where(defined_at=path)` returns exactly the right
entities and respects supersession (a symbol whose `defined_at` moved stops
matching its old path). It is not indexed. Measured on a laptop, SQLite backend:

| Symbols in KB | Lookup per path |
|---|---|
| 6,000 | 3.3 ms |
| 30,000 | 29 ms |

That is worse than linear. For scale: bound names (ADR-0003 Amendment 1) make
Plumbline's symbol count about 3.5× the number of definitions (268 symbols for
76 definitions in this repository), so the PRD's 10k-symbol reference
repository is more like 25–35k symbols here, about 25–30 ms per path: ~1.5 s for
a 50-file push against a 60 s budget, and minutes for a 3k-commit backfill
against 2 h. Comfortable, but it grows faster than the repository does.

**2. The importer stays silent in cases that are not removals.** A symbol can
vanish from the importer's output while still existing: a file that no longer
parses (the importer returns nothing for it), a name that is now defined twice
(it abstains from that name), and members of a class that became ambiguous. A
naive "absent means removed" rule would turn each of these into a false
"removed", and a wrong removal is a false drift report, the one thing the
product must not produce (PRD §3, principle 3).

**3. Two files can claim the same symbol key.** Run on real packages, the
importer's output crashed the assembler: `from . import migrations` in a
package's `__init__.py` binds an *attribute* with the same key as the
`migrations.py` *module*, so one key arrives with two kinds and two
`defined_at`s. It occurs in 4 of Ontolith's 1.8k symbols and 2 of Typer's 681.
The zoo never exercised it. In an incremental ingest, where only the changed
file is read, there is no crash at all but something worse: the entity's `kind`
and `defined_at` would flap between the two owners as each file changes, and
"symbols defined in this path" would give wrong answers.

**4. Deleted files and renames are visible only as paths.** `changed_paths`
lists a deleted path, but its content cannot be read. A rename appears as the
old path deleted and the new one added. Symbol keys are module-qualified, so a
moved file's symbols get new keys anyway; the old keys must be marked removed.

## Decision (proposed)

### 1. A key has one owner; the owner is the path in `defined_at`

Give each kind a rank: `module` (3) > `class`, `function`, `method`, `ambiguous`
(2) > `attribute` (1). When an incoming claim set for a key has a different
path than the KB's active `defined_at`:

- a **higher** rank takes the key over (the module beats the import that
  re-exports it), and `kind` and `defined_at` supersede normally;
- a **lower or equal** rank is dropped and counted as a *conflict* (first writer
  keeps a tie).

The same-path case is the ordinary diff of ADR-0004. Conflicts are reported,
not hidden (see Consequences).

### 2. Removal is inferred only for symbols the changed file owned

For each changed path `P` that was **deleted** or **analyzed**, the use case asks
the KB for the symbols with `present = true` and `defined_at = P`. Any of them
that is not in this commit's snapshot is removed: write `present = false`,
`valid_from` = the commit time, with `source` = an anchor to the commit and
that path (line 1), which records *when and where* absence was observed. The
symbol's other fields keep their last values and open windows; consumers read
`present` first.

A path is **analyzed** iff the snapshot contains a `module`-kind symbol whose
`defined_at` is that path. A changed path that exists but yields no module
symbol (a file that does not parse, or one the importer cannot read) is **left
untouched** and counted as *unanalyzed*; it is never evidence of removal.

A candidate is **not** removed if any ancestor of its key in the snapshot has
`kind = ambiguous` (members of a class that became ambiguous).

### 3. Ambiguity becomes observable

When a name is defined more than once, the importer emits `exists` and
`kind = ambiguous` for it and nothing else, instead of emitting nothing. The
symbol is then present in the snapshot, so it cannot be mistaken for a removal;
its detail facts stay at their last values; and the projector abstains on any
symbol whose `kind` is `ambiguous`. When it becomes unique again, normal diffing
resumes.

### 4. Port and contract changes

- `KnowledgeBase.symbols_defined_in(path) -> list[str]`: keys with an active
  `present = true` and `defined_at = path`, implemented with the query above.
- `CommitRef.changed_paths` must list **both** old and new paths of a rename and
  every deleted path, i.e. the reader runs Git with rename detection off.
- The use case needs the repository slug to build the removal anchor.

## Alternatives Considered

- **A. Path-keyed inference with ownership and an analyzed marker (proposed).**
  Work is proportional to the files that changed; correctness rests on the
  three guards above.
- **B. Compare the entire symbol set every commit.** Simple and self-healing,
  but it reads the whole tree per commit, which contradicts churn-proportional
  work (PRD §7.7). Worth keeping as an occasional repair command, not the
  per-commit path.
- **C. A per-file manifest entity in the KB** (`SourceFile` listing the symbol
  keys it owns). O(1) lookup and an explicit place to record "unanalyzed", at
  the cost of a new concept and one more thing to keep consistent. This is the
  **fallback**: adopt it if path lookup exceeds ~100 ms p95, which the numbers
  above put around 100k symbols. Until measured to matter, the query is enough.
- **D. Let the importer emit tombstones** given the previous symbol list. Puts KB
  state inside the importer and ends its being a pure function of the files
  (which is what makes it testable and sandboxable, PRD §7.8). Rejected.
- **E. Infer removals from Git's rename and delete detection.** Gives file-level
  moves but nothing about a symbol removed from a file that still exists.
  Useful later for the rename hint (DRF-6), not as the mechanism.

## Consequences

- `present = false` finally exists, so PRD §14 #5 and #6 become end-to-end
  testable. The zoo's labeled `exists` true→false supersessions, which the
  assembler tests currently skip, become real checks of the `present` field.
- The importer gains one behavior (`ambiguous`); the assembler gains one kind;
  the use case gains the removal pass and the ownership rule; the adapter gains
  one query. `kind` gets a fifth value, so ADR-0004's table needs a line.
- New zoo scenarios: a file deleted; a symbol removed from a file that stays; a
  rename (old keys removed, new keys added); an edit that breaks syntax (symbols
  untouched, file counted unanalyzed); a name that becomes duplicated (ambiguous,
  not removed) and then unique again; a class that becomes ambiguous (members
  kept); the `from . import sub` collision in both orders; a removed symbol that
  comes back.
- The use case starts returning a small report (unanalyzed paths, ownership
  conflicts) so these cases are visible instead of silent. How it is surfaced
  (`plumb status`, a coverage section) is a later, separate decision.
- Removal is conservative by construction: every uncertain case leaves the KB
  as it was, which can only delay a true drift report, never invent one.

## Open questions (resolved)

All four recommendations were accepted as written: module > definition > attribute
with the first writer keeping a tie; a file that stops parsing leaves its symbols
untouched; `kind = ambiguous` for duplicate definitions; and the per-file manifest
entity is deferred until path lookup is measured to matter.

1. **Ownership ranks and "first writer keeps a tie".** Is module > definition >
   attribute the right order, and is keeping the first writer on a tie
   acceptable (it makes two files defining the same module key a reported
   conflict rather than a flip-flop)?
2. **An edit that breaks syntax leaves the file's symbols untouched.** I
   recommend this over marking them removed: a half-typed file in a PR must not
   open a wave of false drift. The cost is that a genuinely unparseable file's
   symbols go stale until it parses again. Agreed?
3. **`kind = ambiguous`** as the way to make duplicate definitions visible.
4. **The manifest-entity fallback** is deferred until path lookup is measured
   to matter (~100 ms p95). Acceptable, or do you want the index from the start?

## Related, not decided here

The `Fact` slots a removed symbol leaves behind (an `exists` claim in a README
that now disagrees with a `present = false` symbol) are the projector's job
(M1). This ADR only makes the L1 truth available to it.
