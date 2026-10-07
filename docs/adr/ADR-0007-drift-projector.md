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
  or CHANGELOG importers. Every labeled L2 outcome in the zoo is checked through the whole
  pipeline, with `plumb-readme`, `plumb-docs` and `plumb-changelog` claims supplied by a
  test double that emits exactly what the labels say (`tests/zoo/standins.py`). That tests
  the projector, the pass order, and Ontolith's routing for real. Whether a future real
  importer extracts the same claims is that importer's own test, against the same labels.
- **Known limits, accepted.** A required parameter and a non-literal default are
  indistinguishable in `signature_json` (ADR-0004), so a documented default can only be
  checked where the code states one. A submodule the importer never analyzed (excluded,
  or unparseable) under a closed package would be projected absent.

## Amendment 2: what the first real run showed

- **Same-file wrappers built with `functools.wraps` preserve the signature.** §5's short
  allow-list was too blunt: 44 methods of Ontolith's storage backend sit behind a `@wraps`
  locking decorator defined in the same file and lost their signatures. A decorator (or
  decorator factory) defined in the same file that wraps with `@wraps` is now treated as
  signature-preserving. An imported decorator is still opaque, since a single-file analysis
  cannot see into it.
- **A parameter declared `*name` or `**name` exists under its bare name.** A docstring that
  documents `concepts` for `def f(a, *concepts)` is right. Such a parameter still has no
  default or type to project.
- **Withdrawal across time** is recorded in ADR-0004 Amendment 2: the stale signature that
  made existing parameters look missing was the most serious defect found.

See [the first run on a real repository](../first-real-run.md).

## Amendment 3: what measuring precision on real code showed (proposed)

[The seeded-drift evaluation](../seeded-drift-evaluation.md) found that recall is not the
problem: every injected drift was found. Precision is. An unmodified, released package
(`rich`) opened hundreds of contradictions, and reading them showed that most of the
type-related ones are not drift. The cause is in how types are compared, which this ADR
had left to string equality. Four changes follow, in the order they matter.

### A. One canonical form for a type, applied to both sides

Ontolith routes by value equality, so two statements agree only if they are stored as the
same string. "Equal by meaning" therefore has to be made true in the stored values, by one
function used by the code importer and the docstring importer alike. The canonical form:

- removes quotation marks anywhere in the annotation, not only around the whole of it
  (`Iterable['Segment']` and `Iterable[Segment]` are the same type);
- drops a `typing.` or `typing_extensions.` qualifier;
- spells the builtin generics in lower case (`List` and `list`, `Dict` and `dict`, `Tuple`
  and `tuple`, `Set`, `FrozenSet`, `Type`);
- rewrites `Optional[X]` and `Union[A, B]` as unions, and orders the members.

Today the importers already do the fourth step and the qualifier removal for a plain
annotation. They do not remove quotation marks nested inside an annotation, and nothing
lower-cases the builtin generics.

### B. Nullability is not compared

`None` is dropped from a union that has other members, in the canonical form. A bare `None`
(a return type) is kept.

This is a deliberate loss. Drift that only adds or removes `None` from a type will not be
reported. The evidence for accepting it: in the measured package, the large majority of
type findings that differed only by `None` came from a docstring entry that itself says
`optional`. In the Google docstring style `optional` means *the argument may be omitted*,
which is true of any parameter with a default and says nothing about `None`. The tempting
alternative, adding `| None` when a docstring says `optional`, asserts something the author
did not write and would turn `x: int = 1` documented as `(int, optional)` into a false report.
If nullability drift proves worth finding it should be its own aspect with its own rule,
not a side effect of a type comparison.

### C. A type disagreement that cannot be proven abstains

After A and B, if the code's type and a doc claim's type still differ, the projector does not
state the code's type when the difference is not provable:

- either type contains a name that is **not resolved**, where resolved means a builtin or a
  name from `typing` or `collections.abc`. Any other name may be an alias for something the
  documented type is a case of (a `Literal` alias documented as `str`, a union alias
  documented as one of its members), and a single-file analysis cannot see through it; or
- one side is a bare generic and the other a parameterization of it (`Callable` documented
  against `Callable[[Any], Any]`): the docs left the parameters out.

When both types are made only of resolved names and still differ (`int` against `str`,
`Iterable[int]` against `List[int]`), the projection is stated and the disagreement is
reported as before.

The cost, stated plainly: swapping one user-defined class name for another
(`Style` for `Segment`) is no longer reported, because either could be an alias. This is the
abstention-first rule applied consistently, and it is the right place to revisit once a
symbol resolver exists (PRD ING-6).

### D. Two smaller corrections from the same reading

- **A quoted word is not the keyword.** In `Justify method: "default", "left", "right"` the
  word *default* is a value, not "defaults to". The docstring importer must read
  `default(s) to/is/=/:` only outside quotation marks, and as a stated default only when a
  value follows.
- **An integer-valued float and the integer are the same default.** `100` and `100.0` compare
  equal in a signature. The canonical literal for a float with an integer value is the
  integer's, except that a `bool` is never treated as a number.

Left alone, on purpose: a default written with backticks (``Defaults to ``None```) is not read
by the docstring importer at all, which is a recall gap and not a precision problem; and a
docstring that spells a newline as `"\\n"` genuinely disagrees with the code, if only
cosmetically.

### Consequences

- **The projector's input widens, for type slots only.** Abstention under C needs the values
  of the doc claims on the slot, and the plan step currently receives only *how many* new doc
  claims a commit asserts (`DocChanges.asserting`). It must carry the values. The rule stays
  pure: a function of the code's state and of the doc values.
- **A projection can now come and go as the docs change.** A slot that abstains because the
  doc says `str` stops abstaining when the doc is edited to `Style`. The four-pass order
  already handles a projection appearing or leaving per touched fact; a projection that is a
  party to an open dispute is deferred and reported, as before.
- **Stored values change.** Type and default claims written before this change are in the old
  form. The canonicalizer version bump already triggers a re-projection (PRD §7.4, ING-5), and
  doc claims are re-extracted when their file is next touched.
- **Recall must be re-measured.** The injected type drifts (`int` for `str` and back) are made
  of resolved names and must still be found. This is the check that C did not buy precision by
  going blind: the evaluation is re-run and the result recorded, including any category that
  falls.

### How it will be verified

1. Property tests that the canonical form is idempotent, ignores member order and quotation,
   and never makes two types with different resolved names equal.
2. Zoo scenarios for each kind: representation-only, `optional`, an unresolved alias, a bare
   generic, and a resolved disagreement that must still be reported.
3. The seeded-drift evaluation re-run on `rich` and on Ontolith. Recall on injected drift
   must not fall. The unmodified `rich` findings are re-read, and the write-up says how many of
   the earlier false positives are gone, and what is left and why.

## Amendment 4: nullability is compared after all (revises Amendment 3 B)

Amendment 3 B decided that `None` is never compared. Implementing it ran into the zoo
scenario `type_omits_none` and, behind it, PRD §14 Worked Example #10: a docstring that says
`int` against an annotation `int | None` is **real drift** ("the docs omit `None`"), with the
per-fact waiver as the escape hatch for a team that finds it noisy. Amendment 3 B overrode that
without saying so. This revises B so that the PRD example holds, and keeps what B was for.

### What B was for, measured

Reading the docstrings of the package that prompted B (docstring entry against annotation):

| Docstring says `optional` | Annotation has `None` | Entries |
|---|---|---|
| no | no | 297 |
| no | yes | 19 |
| yes | no | 218 |
| yes | yes | 166 |

- **Docstring says `optional`, annotation has `None` (166).** These agree, and under string
  comparison they were reported as disagreeing. This is most of what B set out to remove.
- **Docstring says `optional`, annotation has no `None` (218).** In the Google style `optional`
  means *the argument may be omitted*: it is true of every parameter with a default. Stating
  `| None` for these in the code's favour would be wrong, and reporting them is the false
  positive B warned about.
- **Docstring does not say `optional`, annotation has `None` (19).** This is Worked Example #10,
  and these are the findings B would have thrown away.

### The rule

1. **The canonical type form keeps `None`.** `Optional[X]` and `X | None` are the same thing, and
   `X` is a different one. (This reverses Amendment 3 B's dropping of `None`; the rest of A stands.)
2. **A docstring that says `optional` states that `None` is allowed.** The docstring importer
   adds `None` to the type it claims when the entry says `optional` (Google `(int, optional)`,
   NumPy `int, optional`), unless the type already contains it. So `(StyleType, optional)`
   against `Optional[StyleType]` agree.
3. **The projector abstains when the only difference is that the docs allow `None` and the code
   does not.** That is the 218: `(int, optional)` against `int = 5`. The docs permit omission and
   the code is stricter, which is not provably wrong. The reverse (code allows `None`, docs do
   not) is reported, as Worked Example #10 requires.
4. Amendment 3 C stands for everything else, and is applied to what is left once `None` is set
   aside: unresolved names and bare generics abstain; a disagreement made only of resolved names
   is reported.

### Cost

A docstring that spells out `Optional[int]` or `int | None` itself, against code with no `None`,
now abstains instead of being reported, because it cannot be told apart from the `optional`
case. That is the abstention-first rule, and it is the smaller loss.

### What implementing it showed

- **The cost of Amendment 3 C was larger than stated.** It is not only one user-defined name
  swapped for another: a user-defined class swapped for a builtin (`-> Style` to `-> str`) is
  also withheld, because either could be an alias. Re-running the seeded-drift evaluation on a
  package whose docstrings state types, more than half of the injected type drift was
  withheld this way, and every one of those was a difference the rule calls unprovable. See
  [the evaluation](../seeded-drift-evaluation.md).
- **A `Literal[...]` documented as its value type was reported, and now abstains.** It is a
  correct, looser doc. A difference is not provable when one side is only `Literal` values of
  types the other side names (`Literal['r', 'rb']` against `str`, `Literal['a', 1]` against
  `int | str`). A `Literal[1, 2]` documented as `str` is still reported, because the values are
  not strings.
- **Names that are classes of the repository could be resolved,** which would recover most of
  the withheld drift. That needs import resolution (PRD ING-6), and is not decided here.

## Amendment 5: what three further packages showed about precision (proposed)

[The measurement](../precision-on-three-packages.md) read 317 findings on three packages the
tool had never seen; 180 were false positives, from four systematic causes. Amendments 3 and 4
fixed the cause that dominated on the one package they were tuned on. This records the rules
for the rest, and one decision that is a policy choice, made by the maintainer.

(Properties and the code-side half of deprecation are ADR-0004 Amendment 3.)

### A. A deprecation directive deprecates the symbol only at its top level

The docstring importer reads `.. deprecated::` anywhere as "this symbol is deprecated". In the
packages measured, 28 findings came from a directive **nested in a parameter's description**,
where it deprecates that keyword, or from one that says "This keyword is ignored".

A directive counts only if it is at the docstring's base indentation (the indentation of its
summary and sections, not inside an indented parameter or block), **and** its first sentence
does not begin "This keyword", "This parameter", "This argument" or "This option". Anything
else is ignored, which can only remove a claim.

### B. A documented `default None` allows `None`

Amendment 4 reads a documented `optional` as allowing `None`. A documented default of `None` says
the same thing, and numpydoc writes it more often than `optional` (`min_periods : int, default
None`). The docstring importer adds `None` to a parameter's type claim when the entry's stated
default is `None`, exactly as it does for `optional`. The projector's rule is unchanged: docs that
allow `None` where the code does not abstain; docs that omit it where the code allows it are still
reported (PRD §14 #10), and a docstring that says neither `optional` nor `default None` is that
case.

### C. Docs that are looser than the code do not differ provably

If, for every member that differs, the docs name a supertype of the code's member, the difference
is not provable. A small fixed table of the relations between resolved names is used (never read
from the interpreter):

- `object` and `Any` are the top types, equal to each other and a supertype of every resolved
  name, including `Hashable`;
- `list`, `tuple` and `str` are `Sequence`; `Sequence`, `set`, `frozenset` and `dict` are
  `Collection`; `Collection` is `Iterable`; `dict` is `Mapping`; `set` and `frozenset` are
  `AbstractSet`.

A supertype is compared by its head, and only where the arguments are equal or the docs are bare
(`list[str]` documented as `Sequence[str]`). The reverse, docs *narrower* than the code (`Sequence`
in the code, `list` in the docs; `Hashable` against `str`), is still reported: the docs promise
less than the code accepts, which is a real if small imprecision.

### D. A `None` default is a sentinel (decided by the maintainer)

When the **code's** default is `None` and a doc claim states a concrete, different default, the
projector does not state the code's default. `None` as a default usually means "computed or
unset", so the docs' effective default (`engine=None` documented as `default 'numexpr'`) is not
provably wrong. In the packages measured this was 43 findings, a policy question and not an error
the tool made.

Unchanged: a concrete code default against a different concrete documented default (`axis=0`
against docs saying `None`) is reported, and so are docs that say `None` where the code has a
value.

*Cost.* A docs default that really is stale behind a `None` sentinel is no longer reported.
Waivers (DRF-7) would have been the way for a team to silence these one at a time; this removes
the need for the common case at the price of that recall.

### What the changes cost, together

Each change withholds a report the tool previously made, so recall on drift of those kinds falls
by design. The injected-drift evaluation reports what is withheld separately from what is missed,
and will be re-run with a category for each.

### What implementing it showed

- **Looser docs and an omitted `None` interact.** The bare-generic rule (Amendment 3 C) used to
  abstain first; the looser-docs rule now runs first and still reports an omitted `None`, as C says.
  Three findings that were silent are now reported: `dict[...] | None` in the code against a bare
  `dict` in the docs. They are PRD §14 #10 cases.
- **The fixes did not generalize.** On three packages the rules had never seen, 17 of 22 findings
  were false, from three causes this amendment does not cover: a signature with `*args` (a
  documented name may be what it receives, as `**kwargs` already makes a missing keyword
  unprovable), deprecation through a helper whose name says so but is not `warn`, a `.. deprecated::`
  note that begins "The *x* parameter", and a docstring template placeholder. They need their own
  amendment and a fresh set of packages. See
  [the report](../precision-on-three-packages.md).

### How it will be verified

1. Unit and property tests per rule, and a zoo scenario per cause, each run through the real
   importers, projector and Ontolith routing.
2. The measurement on the same three packages and on `rich`, repeated, with the numbers set beside
   the ones in the report. A finding that was REAL must not disappear unless it falls under a
   rule above, and any that does is listed.
3. The seeded-drift evaluation re-run: recall on provable drift must not fall, and the withheld
   count is reported.
4. A second reader labelling a sample of what remains, because every label so far is mine.

## Amendment 6: `*args`, parameter notes, and what a deprecation note is (proposed)

Three causes of false positives came out of packages the earlier rules had never seen
([report](../precision-on-three-packages.md)). The first set of packages that revealed them is
now spent for tuning; these rules are to be tested on packages chosen beforehand and not yet read.

### A. `*args` makes a missing positional parameter unprovable

`param.<p>.exists` is stated `false` only if `p` is not a named parameter **and the signature has
neither `*args` nor `**kwargs`**. Today only `**kwargs` is considered. `pts_to_midstep(x, *args)`
documents `y1` and `yp`, which are what `*args` receives; `Bbox.from_extents(*args)` documents
`left`, `bottom`, `right`, `top`. In the three held-out packages this was 14 of the 22 findings (and of the 17 false ones).

*Cost.* A parameter documented on a function with `*args` that really does not exist is no longer
reported.

### B. A deprecation note is about a parameter if it says so, wherever it sits

Amendment 5 A tested the **first line after** the directive, and required that line to be
indented. Two gaps:

- `.. deprecated:: 3.11` followed by a **blank line** and then the note (the usual numpydoc
  layout) was read as having no note, so it counted as deprecating the function.
- The note was recognized only when it began "This keyword/parameter/argument/option".
  `matplotlib.ScaleBase.__init__` has a directive in a *Notes* section reading "The *axis*
  parameter is now optional…".

The note is the **first non-empty line after the directive**, indented or not. It is about a
parameter if it begins `This` or `The`, optionally followed by one name (`*axis*`, `` `copy` ``,
`axis`), and then `keyword`, `parameter`, `argument` or `option`. Such a directive is ignored.

### Not included, on purpose

A docstring template placeholder (`DATA_PARAMETER_PLACEHOLDER`, filled in by a decorator elsewhere)
was one finding, in one project's convention. A rule for it would be shaped to that project, and
one instance does not show it recurs. It is recorded as a known limit.

### What implementing it showed

- **The rules did what they were written to.** On the packages they were derived from, the 16
  false positives went and nothing else changed, except two real findings on `rich` (stale doc names
  for a parameter that `*args` receives), which is the stated cost.
- **They barely touched the fresh set.** Of 192 findings on five packages baselined beforehand, the
  rules removed 8. 44 of the remaining 184 are false, from four further causes (a section
  underlined with `=`; comma-separated alternative types; a deprecation note about a usage, or a class
  that warns from `__init__`; five single cases) and 79 are narrower-docs findings. See
  [the report](../precision-on-three-packages.md).
- **Two questions are policy and not defect.** Whether docs naming a subtype of the annotation
  (`dict` for `Mapping`) are drift, and whether the `| None` in a sentinel-default parameter's type
  is. Neither is decided here.

### How it will be verified

1. Unit tests per rule and a zoo scenario per cause, each with the neighbouring case that must
   still be reported (a documented parameter on a function without `*args`; a directive with
   an ordinary note).
2. Five packages chosen and baselined **before** this amendment was written (`xarray`, `astropy`,
   `dask`, `seaborn`, `sympy`: 192 findings in total) are read only after the rules exist, and the
   result is reported whatever it is, including new causes.
3. The earlier packages are re-run as a regression check only: a finding I labelled REAL must not
   disappear.
