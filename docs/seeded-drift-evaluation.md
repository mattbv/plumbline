# Seeded-drift evaluation

[The first real run](first-real-run.md) found nothing once its own bugs were fixed, and zero
findings on a carefully documented project looks the same as a tool that cannot see anything.
This measures the two things that could not be told apart: **does it find drift that is really
there** (recall), and **does it report drift that is not** (precision).

Run it with `uv run python -m evaluation.seeded_drift --repo PATH`. It works on a scratch clone, so
the repository measured is only read. The code is in `evaluation/`; it is not part of the shipped package.

## Method

- The baseline history is ingested with the same pipeline `plumb ingest` uses
  (`plumbline.interfaces.pipeline`), so the measurement says something about the tool and not
  about a look-alike.
- Each injection is a **real Git commit** on the clone, ingested incrementally. A contradiction
  that is new afterwards is attributed to that commit. Each function is touched at most once, so
  attribution is unambiguous.
- Injections are chosen from facts the tool already corroborates, and edited with the `ast`
  (exact spans, not text search), on both sides: **code drifting from the docs** (a default, a
  parameter type, a return type, a renamed parameter) and **docs drifting from the code** (a
  stated default, a stated type, a documented parameter that does not exist, a `deprecated`
  directive the code does not have).
- **Controls** must *not* be reported: a comment, a harmless statement, a new undocumented
  function, a reworded summary, and a default or type changed where the docstring says nothing.
  They measure false positives under churn.
- A removed `raise` is reported separately. A `Raises:` entry can never be proven wrong (absence of
  a raise is unprovable), so silence there is by design, not a miss.
- An injection counts as **found** only when the expected fact opened with the expected code and
  docstring values. The right fact with the wrong values is counted separately.

The harness is itself tested (`tests/unit/evaluation`): its edits are checked to touch exactly one
thing; it must report a miss when the tool is made to find nothing; it reports requested against
executed injections per category; and a run that injects nothing **fails** instead of printing
"0 missed". That last rule exists because the first version printed `RECALL 1/1 = 100%` after
being asked for three of each, and `0/0` on a fixture too small to inject anything.

## Results

| Repository | Injected drift found | Controls reported | Extra findings on injections |
|---|---|---|---|
| `rich` (3 seeds × 90 injections) | 90/90, 90/90, 90/90 | 0/60 each | 0 |
| Ontolith (2 seeds × 34 injections) | 34/34, 34/34 | 0/60 each | 0 |

Every injected category was found every time it was injected: default, parameter type, return
type and renamed parameter in code; stated default, stated type, invented parameter and
`deprecated` in the docs.

**Read the Ontolith row narrowly.** Ontolith's docstrings state no types and almost no defaults
(`Args: name: description`, with types in the annotations), so the four type categories got no
injections at all and the two default categories got two. The 34 are existence-style drift only.
The harness prints this as a shortfall; it does not average it away.

## The finding that matters more: precision on real code

`rich` is a released package. **Before anything was injected, the unmodified copy had 228 open
contradictions.** These are what a user would see on the first run. I went through them.

| What | Count | Reading |
|---|---|---|
| Type disagreements | 191 | see below |
| Documented parameter that does not exist | 12 | all real documentation defects, checked against the source (e.g. docs say `width`, code says `widths`; a docstring that names `max_frames`, which the code has never had; `int (size)` with the type and name swapped) |
| Default disagreements | 25 | 14 read: 6 real (a stated `False` against code `True`), 5 an over-escaped `"\\\\n"` in the docs, 2 a tool error, 1 benign (`100` against `100.0`); 11 not read |

Of the 191 type disagreements, split by a normaliser I wrote for the purpose:

- **21** differ only in representation: quotes around a forward reference (`'Segment'` against
  `Segment`), a `typing.` prefix, `List` against `list`, union order.
- **106** differ only by `None` / `Optional`. In **86** of them the docstring entry itself says
  `optional` (`style (Style, optional)` against `Optional[Style]`), which by the convention the
  docstring uses says exactly what the annotation says. In 17 it does not.
- **64** remain different. Some are real (`Iterable[int]` documented as `List[int]`); many are an
  alias the tool cannot see through (`JustifyMethod`, a `Literal` of strings, against a documented
  `str`), where the tool cannot prove the two differ.

**At least 110 of the 228 (48%) are false positives**: 21 + 86 representation and `optional` cases,
2 that are a tool error, 1 benign. That is a lower bound; 75 findings were not read. It is **far
below the ≥90% precision the plan asks for on real code**, and the cause is not subtle: the
projector compares type strings that differ in representation, and treats a documented
`optional` as a disagreement.

The tool error: `Justify method: "default", "left", ...` produced `param.justify.default = ', '`,
reproduced in isolation. The importer takes the quoted word *default* for the keyword and then
matches the quote characters that follow. Five of the `end` findings I read are the docs' own
over-escaping, which is real but cosmetic.

## What this does and does not show

- Recall is high **for drift in a form the importers extract**. An injection is chosen from a fact
  already corroborated, so drift in a claim the tool never extracts (prose in a README, a
  type written in a form it does not parse) is invisible to this measurement by construction.
- The injections are clean, single, well-formed edits. Organic drift is messier. A recall of 100%
  here is a floor on what is detectable, not a forecast.
- 10 injections per category and three seeds is enough to show nothing is badly broken, not to
  put a tight interval on a rate.
- `rich` here is the installed copy as one commit, so it carries no history. The history path is
  covered by [the first run](first-real-run.md) and by the Git equivalence tests; the incremental
  path is what each injection exercises.
- Only docstrings are read. README, docs-page and CHANGELOG claims are not yet extracted.

## What it points to

The tool finds what is there. The work is in not reporting what is not:

1. Compare types modulo representation, and modulo `optional` as the docstring uses it. This
   changes what the projector treats as a disagreement, so it needs an ADR amendment before code.
2. Abstain where an alias the tool cannot resolve stands against a documented base type.
3. Fix the quoted-word default parse.
4. Measure precision again on `rich`, and on a third repository, before calling the M1 precision
   criterion met or not.
