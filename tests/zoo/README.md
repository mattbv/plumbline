# The drift zoo

A synthetic Git repository of **seeded, labeled drift scenarios** (PRD §10 M0).
It is the ground truth Plumbline is measured against: M0's exit criterion is that
ingesting it is deterministic and every scenario's routing outcome is asserted;
M1's is precision ≥ 95% and recall ≥ 90% against it.

Nothing in `src/` depends on this package. It lives under `tests/`.

## How it is organised

| Module | Role |
|---|---|
| `model.py` | `Scenario`, `Commit`, `Expectation` -- pure data |
| `scenarios/` | The scenarios, grouped by theme (`signatures`, `abstention`, `history`) |
| `oracle.py` | An independent statement of the PRD's routing rules, and a linter that checks every label against it |
| `builder.py` | Materializes scenarios as one real Git repo whose SHAs are identical on every build |

Each scenario is a tiny project with its own package, README, docs and CHANGELOG,
placed under `scenarios/<id>/` in the built repo so scenarios never collide.
Symbol keys start with the scenario id: `py:<id>.<module>.<name>`; project-level
facts use `project:<id>` (a provisional convention -- the PRD does not fix one).

## Expectations

An `Expectation` says what must be true **after** a commit is applied, for one
`(symbol, aspect)` slot:

| `layer` | `outcome` | Meaning |
|---|---|---|
| L1 | `supersede` | The code value changed; the old window closed; no review (§7.1) |
| L2 | `corroborate` | The code projection and every doc claim agree; all kept, never merged |
| L2 | `contradict` | Members disagree; flagged and routed to review. Needs a `drift_class` (DRF-4) |
| L2 | `abstain` | Doc claims exist but the projector cannot determine the code value (DRF-3) |
| L2 | `undocumented` | No doc claim to compare against |

`abstain` and `undocumented` are **not drift** (DRF-5); they are separate coverage
states, kept distinct so the M1 report can count them separately. The M0 exit
criterion's four outcomes (supersede / contradict / corroborate / abstain) are
the first four rows.

`code_value` is the canonical value the projector asserts (`None` = it abstains).
`claims` are `(importer principal, canonical value)` for each active doc claim.
Values must already be in canonical form (`plumbline.domain.canonical`); the
linter rejects anything else.

## Closure expectations

A `ClosureExpectation` labels the `namespace_closed` value (ADR-0003) the code
importer must emit for a module or class after a commit. `closed=True` means
every name in that namespace is determined by the source, so a documented name
that is missing is *drift*; `closed=False` means something could still supply
it, so the claim stays *unverified* (an `abstain`). Pair each closure label with
the L2 expectation it explains.

## State expectations

A `StateExpectation` labels what the **stored** L1 state of a symbol must be after a
commit is ingested: `present`, and optionally `kind` and `defined_at`. It is the only
way to express removal and, just as importantly, "left alone" (a file that stopped
parsing must not look like a deleted file). A `Commit` can mark a Python file as
`broken=` when it is intentionally not valid syntax; the linter then checks that it
really fails to parse, and that every other Python file does.

## Adding a scenario

1. Pick the PRD section or requirement it exercises and put it in `prd_refs`.
2. Write the commits as real, parseable Python and Markdown -- the linter parses
   every `.py` at every commit.
3. Label only what the PRD prescribes. If you find yourself inventing semantics,
   stop and record an open question instead.
4. Add it to its module's `SCENARIOS` tuple and run `uv run pytest tests/unit/zoo`.

The linter derives each outcome from the slot's inputs and fails if your label
disagrees. If you believe the oracle is wrong, that is a PRD question, not a test fix.

## What is not here yet

- PRD §14 #9 (an agent's hallucinated fix) needs the shadow-KB flow -- M2.
- The wiki source (ING-3, P1) -- it is a second Git repository.
- Resolution lifecycles (resolve, waive, re-affirm, revert) -- M2.
- Roughly 60 more scenarios to reach the PRD's ~80.
