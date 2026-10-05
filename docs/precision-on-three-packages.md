# Precision on three more packages

[The seeded-drift evaluation](seeded-drift-evaluation.md) took the findings on one package,
`rich`, from 228 down to 49 and found none of the remaining ones false. That was one package,
and it was also the package the fixes were tuned on. This measures the same thing on three
packages the tool had never seen.

**It did not generalize. On these three packages, 180 of 317 findings (57%) are false
positives, and the M1 criterion is ≥90% precision on real code.** The plan's M1 precision
criterion is not met, and the `rich` result should not be read as evidence that it nearly is.

## What was measured

Three packages, each ingested as a single commit (no history) with the same pipeline as
`plumb ingest`, taking every open contradiction as a finding:

| Package | Wheel | Docstring style | Findings |
|---|---|---|---|
| `boltons` | 26.2.0 | Google | 3 |
| `networkx` | 3.7 | NumPy | 43 |
| `pandas` | 3.0.6 | NumPy, annotated code | 271 |

They were chosen from ten candidate packages ranked by typed docstring entries, to cover
different docstring styles and amounts of annotation; they are not the three highest. The wheels
were unpacked and read statically; nothing was run.

**The labels are mine.** One reader, no second opinion. For `exists` and `deprecated` findings I
checked each against the source, some by reading and some mechanically (by decorator, by where a
directive sits, by whether the body warns). Defaults and types I classified by pattern and
spot-read, which is stated where it matters below. A second reader is exactly what this needs.

Labels: **REAL** (docs and code disagree and a reader could be misled), **SENTINEL** (the code
defaults to `None` and the docs state the effective value, so the docs are arguably right: a
true finding, but one a team might call noise), **FALSE** (the tool misread something).

## Result

| Package | REAL | SENTINEL | FALSE | Total |
|---|---|---|---|---|
| `boltons` | 1 | 2 | 0 | 3 |
| `networkx` | 0 | 1 | 42 | 43 |
| `pandas` | 93 | 40 | 138 | 271 |
| **All** | **94** | **43** | **180** | **317** |

Strict precision (REAL only) is **30%**; counting SENTINEL as true it is **43%**.

Counts overstate the number of defects. For example 16 of the `pandas` findings are one stale
docstring copied across the window-indexer classes. The false positives are not like that:
they come from four systematic causes, below, and each would recur on any package that
documents things the same way.

## The four causes of false positives

**1. Parameters documented on a property (39, all `networkx`).** `Graph.edges` is a
`@cached_property` returning a view, and its docstring documents how to call the *view*
(`edges(nbunch=None, data=False, default=None)`). The tool treats the property's signature as
`(self)` and reports every documented parameter as missing. Every one of the 39 `exists`
findings in `networkx` is on a property.

**2. Deprecation read wrongly, in both directions (39).**
- *The docstring importer* takes a `.. deprecated::` directive anywhere in the docstring as
  deprecating the function. In `pandas` 28 are indented inside a parameter's description
  (deprecating that keyword), or say "This keyword is ignored" (`Series.set_axis`).
- *The code importer* recognizes a `@deprecated` decorator, or a `DeprecationWarning` call as the
  **first** statement of the body. Eleven functions (8 in `pandas`, 3 in `networkx`) warn that
  they are deprecated and are missed, so the code is deprecated and the tool states that it is
  not. The causes I confirmed: in `networkx` the warning is the second statement, after
  `import warnings`; in `pandas` the warning is first, but its category is `Pandas4Warning`, a
  custom subclass, and only the literal name `DeprecationWarning` is matched. I confirmed these
  on `metric_closure` and `is_categorical_dtype`, and did not check each of the other nine.
  `networkx.metric_closure` also carries decorators the importer does not know, so it should not
  have claimed "not deprecated" at all.

**3. A documented `default None` allows `None` (at least 87, `pandas`).** Amendment 4 reads
`optional` as allowing `None`; `pandas` writes `min_periods : int, default None`, which says
the same thing. These are reported as "the docs omit `None`" (PRD §14 #10). At least 87 of the
122 omit-`None` findings in `pandas` already say `default None` or `optional`. The remaining
~35 do not, and are true by the PRD's own definition.

**4. Docs that are looser than the code, not wrong (15, `pandas`).** `Any` against `object`
(9), `Hashable` documented as `object` (5), `list[str]` documented as `Sequence[str]` (1).
Each is a correct, less specific statement.

## What I am least sure about

For a second reader, in order of how much they could move the result:

1. **SENTINEL (43).** Whether a signature default of `None` against a documented effective
   default is drift is a policy question, not a fact. If it is noise, strict precision is the
   figure, and it is lower still.
2. **The ~35 omit-`None` findings I counted as true.** They are true under PRD §14 #10 as
   written. A reader who thinks #10 is too aggressive would move them to false.
3. **The 15 "looser docs" findings.** I called them false; one could argue `object` for a
   `Hashable` parameter is a real, if small, imprecision.
4. **Four type findings I could not settle:** `validate_periods :: periods` (docs type `None`),
   `reset_index :: names` (docs `int`), `Styler.bar :: cmap` (docs `str`), `Styler.to_excel ::
   verbose` (docs `str`). I counted them REAL.
5. **Defaults.** 40 `pandas` defaults were classified as SENTINEL by pattern (code `None`, docs a
   concrete value) rather than read one by one.

Rejecting PRD §14 #10 (item 2) takes strict precision to 59 of 317 (19%). Accepting the 15
looser-docs findings as real (item 3) would raise the lenient figure to 152 of 317 (48%).
Neither moves it anywhere near 90%.

## What this does not show

- Recall on these packages. Nothing was injected; this is only what was reported.
- Behaviour with history. Each package is one commit.
- That three packages are representative. They were chosen from the more heavily documented of
  ten candidates, which favours packages with strong docstring conventions, the ones the tool
  should read best. A sparsely documented package would give fewer findings, not obviously
  better ones.

## What it points to

Each cause above is a defect in what the importers read or what the projector claims, and each
has the same shape as the earlier fixes: the tool stated something it could not prove.

1. Do not state a signature for a property; its documented parameters describe its result.
2. Read a deprecation directive only at function level and not as a keyword's note; recognize a
   deprecation warning that is not the first statement or uses a custom category; abstain on
   `false` where an unknown decorator could be doing it.
3. Read a documented `default None` as allowing `None`, as `optional` is.
4. Treat a documented supertype (`object` for `Any`, `Sequence` for `list`) as not provably
   different.
5. Decide what to do with SENTINEL.

Items 1 to 4 each change what the importers or projector claim, so each needs an ADR amendment
before code. This should be repeated on these same three packages after the fixes, and the
numbers compared with the ones here.
