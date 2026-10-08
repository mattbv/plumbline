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

## After the fixes (ADR-0004 Amendment 3 and ADR-0007 Amendment 5)

The rules in those amendments were implemented and the measurement repeated. Two things are
reported separately because they mean different things.

### On the same three packages: 317 findings became 93

| Package | Before | After | What went |
|---|---|---|---|
| `boltons` | 3 | 1 | 2 sentinel defaults |
| `networkx` | 43 | 0 | 39 property parameters, 3 deprecations, 1 sentinel default |
| `pandas` | 271 | 92 | 36 deprecations, 40 sentinel defaults, 106 type findings (documented `default None`, looser docs) |

No finding I had labelled REAL among the `exists` and concrete-default findings disappeared (24
and 8 in `pandas`; the one in `boltons`). Of the type findings I had counted as true, four went,
and they are cases of a documented `default None` that my earlier check missed because the docs
write "defaults None"; so those were mislabelled, not lost. Three type findings appeared that
were not reported before: `dict[...] | None` in the code against a bare `dict` in the docs with
no `optional` or default stated. They are PRD §14 #10 cases. The bare-generic rule used to
abstain on them first; the looser-docs rule now runs first and, as Amendment 5 C says, still
reports an omitted `None`. That interaction was not spelled out in the amendment.

**This is an in-sample number.** Every rule was designed from these three packages, so "93
findings, all of which I read as true" says the rules do what they were written to do, and
nothing about packages they were not written for. That is the mistake `rich` made.

On `rich`, findings went from 49 to 39 (six sentinel defaults and four documented `default
None`; three of the four I confirmed in the docstring text, the fourth continues on a later line).

### On three packages the rules never saw: 22 findings, 17 false

`matplotlib`, `scikit_learn` and `scipy`, taken untouched. I read all 22.

| Package | Findings | False | Real | Arguable |
|---|---|---|---|---|
| `matplotlib` | 21 | 17 | 2 | 2 |
| `scikit_learn` | 1 | 0 | 1 | 0 |
| `scipy` | 0 | 0 | 0 | 0 |

That is 17 of 22 false (77%), with 3 real and 2 arguable (a colour written `'k'` in the code and
`'black'` in the docs; a default documented as an `rcParam`). A sample this small and dominated
by one cause is a weak estimate, but it is the honest one: **the fixes did not generalize.**

`scikit_learn` and `scipy` give almost nothing because their documented types are prose
(`array-like of shape (n_samples,)`), which the importer correctly refuses to treat as types, and
their code is mostly unannotated. Zero findings there is not evidence of precision.

Three new causes, each from a different mechanism:

1. **A signature with `*args` (14).** `pts_to_midstep(x, *args)` documents `y1` and `yp`;
   `Bbox.from_extents(*args)` documents `left`, `bottom`, `right`, `top`. The documented names
   are what `*args` receives, so their absence is not provable, exactly as `**kwargs` makes a
   missing keyword unprovable. The rule exists for `**kwargs` and not for `*args`.
2. **Deprecation through a helper (1) and through a parameter note (1).** `set_figure` calls
   `_api.warn_deprecated(...)`: a function whose name says so, but not called `warn`. A
   `.. deprecated::` in a *Notes* section whose text is "The *axis* parameter is pending-deprecated"
   deprecates a parameter, and is not caught by the "This keyword…" test.
3. **A docstring template (1).** `data : indexable object, optional` followed by
   `DATA_PARAMETER_PLACEHOLDER`, filled in by a decorator elsewhere.

I did **not** fix these in the same change. Fixing them against the set that revealed them would
spend it, and each needs an amendment first. They need a new set of packages to test against.

### Recall

On `rich`, three seeds: 188 provable injected drifts, all found, 0 of 60 controls reported each
time, and 23, 28 and 31 injections withheld on purpose (it was 26, 25 and 22 before the new
rules). Ontolith: 34 of 34. The harness now also counts a docs default changed behind a `None`
default as withheld, and skips a deprecation injection where the importer cannot say "not
deprecated".

### What the numbers do and do not say

- They say the four causes found earlier are fixed on the packages they were found on, without
  losing the findings I read as real there.
- They do not say precision is near 90%. The only held-out evidence says it is not.
- The remaining 93 are still labelled by one reader. The 34 or so that depend on PRD §14 #10 are
  the ones a second reader could dispute.

## After Amendment 6: five packages chosen and baselined in advance

The rules for `*args`, parameter notes and deprecation helpers (ADR-0007 Amendment 6, ADR-0004
Amendment 4) were implemented, then tried on five packages that had not been used for anything:
`xarray`, `astropy`, `dask`, `seaborn`, `sympy`. Their baseline counts (192 findings) were
recorded **before the amendment was written** and before any finding was read.

**Regression, on the packages already read.** `matplotlib` went from 21 findings to 5, losing
exactly the 14 `*args` findings and the 2 deprecation false positives it had revealed, and nothing
else. `pandas`, `networkx`, `boltons`, `scikit_learn` and `scipy` did not change at all. `rich`
went from 39 to 37, and **both were real**: stale documentation naming a parameter that `*args`
receives (`control_codes` for `control(self, *control)`). That is the stated cost of the rule.

**The rules removed 8 of the 192 fresh findings**, 4%: 1 `exists` in `astropy`, 7 `deprecated` in
`sympy`. Nearly everything on these packages is something the rules were not written for. That
is the result that matters.

### What 184 findings are

I read all 184. Labels: **REAL** (docs and code disagree and a reader could be misled);
**NARROW** (the docs name a subtype of what the code accepts: `dict` for a `Mapping` parameter,
`list` for a `Sequence`; technically a disagreement, and one many teams would not call drift);
**SENTINEL-TYPE** (code `X | None = None`, docs `X, default: <concrete>`: the sentinel idiom
that Amendment 5 D already treats as not drift for the *default*, here showing up in the type);
**FALSE** (the tool misread something).

| Package | Findings | Real | Narrow | Sentinel-type | Arguable | False |
|---|---|---|---|---|---|---|
| `xarray` | 96 | 22 | 64 | 9 | 0 | 1 |
| `astropy` | 43 | 18 | 11 | 0 | 0 | 14 |
| `dask` | 14 | 7 | 4 | 1 | 1 | 1 |
| `seaborn` | 2 | 0 | 0 | 0 | 0 | 2 |
| `sympy` | 29 | 3 | 0 | 0 | 0 | 26 |
| **All** | **184** | **50** | **79** | **10** | **1** | **44** |

**44 of 184 (24%) are false.** Only 50 (27%) are clearly real. 79 (43%) are narrow-docs findings
that depend on a policy call. Counting narrow, sentinel-type and arguable as true, 140 of 184
(76%) are true. None of these figures is near the plan's 90%, and the honest reading is that
**the criterion is not met, and two policy questions decide most of the remaining gap.**

### New causes of false positives (44)

1. **A section underlined with `=` (13, `sympy`).** `Returns\n=======` and `Examples\n========`
   are not recognized as headings, so everything after them is read as parameters: `Examples`,
   `Returns`, `Symbol` become parameters of `Beam.apply_rotation_hinge`.
2. **A comma-separated list of alternative types (13, `astropy`).** `tuple, None`,
   `None, int, or tuple of int, optional`, `list, None, optional (default None)`: the importer
   takes the first part as the whole type (`None`, or `tuple`) and misses `optional (default
   None)`, so the claim is wrong in either direction.
3. **Deprecation: a usage note, and a class that warns from `__init__` (13, `sympy`).** The
   directive says "using arguments that aren't `Expr` … is deprecated" (a usage), or the class
   warns through `sympy_deprecation_warning(...)` in `__init__`, which the class check does not
   enter.
4. **Five single cases:** a `Parameters` section reading `None` is read as a parameter named
   `None`; the prose "…if possible, provided the keyword…" is read as an entry named `possible`;
   `{plot, diag, grid}_kws` is read as a parameter `diag`; `emit_user_level_warning('… is
   deprecated …')` is a project helper whose message, not its name, says so; and a `Returns`
   section listing three values each typed `float` is read as returning `float`.

### The two policy questions

- **NARROW (79).** Is `dict` documented for a `Mapping` parameter drift? It is true that the
  docs promise less than the code accepts. It is also what most numpydoc authors write for the
  common case. Amendment 5 D settled the same question for sentinel defaults by abstaining.
- **SENTINEL-TYPE (10).** If a `None` default is a sentinel, the `| None` in the type is the same
  sentinel. As things stand the default is silent and the type is reported.

### What I am least sure about

- Every label is mine. The 50 REAL include 19 PRD §14 #10 cases (docs omit a `None` the code
  allows) that a reader who finds #10 too aggressive would move out.
- NARROW and SENTINEL-TYPE are classifications I invented to separate a judgement call from an
  error. Where I put the line is itself a judgement.
- The three broad classes (NARROW 79, SENTINEL-TYPE 10, PRD §14 #10 19) were assigned by a script
  and spot-read, not read one by one. The 61 `exists`, `deprecated` and `default` findings and
  the 64 type findings outside those classes were read individually.
- Earlier results counted a narrower-docs finding as REAL (26 in `pandas`). Split the same way,
  those would be NARROW too, and the earlier REAL figures would be lower.

### Recall

On `rich`, three seeds: 188 provable injected drifts, all found, 0 of 60 controls reported each
time (23, 28, 31 withheld on purpose). Ontolith: 34 of 34. One miss appeared along the way and
was the harness's: it renamed a parameter in a function with `*args`, which is now unprovable by
design. The harness's guard now covers `*args` as well as `**kwargs`.

## After Amendment 7: the packages read so far, and a second set read once

The rules in ADR-0007 Amendment 7 and ADR-0004 Amendment 5 (narrower docs, the `None` of a
sentinel parameter, `=`-underlined sections, alternative types, entry names, usage notes,
`__init__` deprecation, message-based notices) were implemented and tried twice.

### Regression: the eleven packages already read, 283 findings became 169

| Package | Before | After | Note |
|---|---|---|---|
| `boltons`, `matplotlib`, `scikit_learn`, `scipy` | 1, 5, 1, 0 | 1, 5, 1, 0 | unchanged |
| `pandas` | 92 | 57 | narrower docs and sentinel types went |
| `xarray` | 96 | 22 | 73 type findings and one deprecation went |
| `astropy` | 43 | 16 | 27 type findings went |
| `dask`, `seaborn` | 14, 2 | 9, 0 | |
| `networkx` | 0 | 2 | two real defaults (`[-]`, `[loop]` documented against the code's `''` and `'edge_options'`), newly readable |
| `sympy` | 29 | 56 | 23 false findings went; **50 appeared** |

The 50 in `sympy` are findings that were always there and could not be seen: its docstrings
underline sections with `=`, which the importer did not recognize, so those sections were never
read. Of the 50, I read 49 as real stale documentation (`fp_group` for `fp_grp`, `elt` for `a`,
`mu`/`sigma` for `mean`/`std`, `ccode`'s `standard` documented `'c89'` against a code default of
`'c99'`) and one as a misreading (a prose line `Note` read as an entry).

### Three defects that the changes themselves introduced, found by this check

The first re-run showed 73 new `sympy` findings, 2 in `networkx` and 1 in `pandas`. Reading them
found three faults in the new code: `codes_given: bool, False` became the union `bool | False`;
a bare list of types under `Parameters` (`Point3D, Line3D, Plane, tuple, list`) was read as five
parameters (10 findings); and a method whose first parameter is not called `self`
(`def angle_between(l1, l2)`) had `l1` reported missing when documented by name (13 findings).
All three are fixed, with tests. Had I not re-run the earlier packages I would have shipped them.

### The second fresh set, read once: 114 findings became 67

Six packages chosen and baselined before the amendment was written, with no finding read until the
rules existed (`statsmodels`, `geopandas`, `bokeh`, `pint`, `altair`, `pyproj`). Five more
(`scikit_image`, `docutils`, `click`, `tqdm`, `shapely`) gave no findings before or after. I read
all 67.

| Package | Findings | Real | By-design | False |
|---|---|---|---|---|
| `statsmodels` | 9 | 2 | 1 | 6 |
| `geopandas` | 3 | 1 | 2 | 0 |
| `bokeh` | 24 | 10 | 14 | 0 |
| `pint` | 5 | 1 | 3 | 1 |
| `altair` | 19 | 0 | 19 | 0 |
| `pyproj` | 7 | 4 | 3 | 0 |
| **All** | **67** | **18** | **42** | **7** |

**Real** is a genuine disagreement (a stale parameter name such as `css_color` for
`css_color_string`, a wrong default, `bytes` documented as `str`). **By-design** is the docs
omitting a `None` the code allows with no `optional` or default stated, which PRD §14 #10 calls
real drift; 42 of the 67 are this. **False** is a misreading: a prose label `TODO:` read as an
entry, the word `optional` read as an entry, and five `0`/`1` defaults documented as
`False`/`True`.

Seven of 67 (10%) are false. Eighteen (27%) are clearly real, and with the by-design cases
60 of 67 (90%) are findings the project's own definitions call true.

### The trend, and what it does and does not say

| Set | Read after | False findings |
|---|---|---|
| First three packages | nothing | 180 of 317 (57%) |
| Held-out set 1 | Amendments 3 to 5 | 17 of 22 (77%) |
| Fresh set 1 | Amendment 6 | 44 of 184 (24%) |
| Fresh set 2 | Amendment 7 | 7 of 67 (10%) |

Every row is a set read once, after rules written from earlier sets and not from it. The rate has
fallen each time. It has not been zero, and each set has shown causes the previous one could not:
the seven here include three the rules do not cover. A fourth set will very likely do the same.

### What I am least sure about

- Every label is mine. `docs/second-reader-sheet.md` holds 30 of the 67, with the code, the docs, the
  signature and the docstring line and **without my labels**, for someone else to mark. The key is not
  in the repository.
- The 42 by-design findings are 63% of the set. They depend entirely on PRD §14 #10. A reader who
  finds #10 too aggressive moves them out, and then 18 of 25 are real.
- Some of those 42 are the sentinel idiom with a sentinel that is not `None`. `altair` defaults to
  `Undefined`, and at least one finding (`transform_quantile`, `step: Optional[float] = Undefined`,
  documented `float` with `default 0.01`) is the same case as the `None` sentinel. Amendment 7 B does
  not cover it.
- One package, `altair`, supplies 19 of the 42.

### Recall

On `rich`, three seeds: 192 provable injected drifts, all found, 0 of 60 controls reported each
time, 25 to 27 withheld on purpose. Ontolith: 34 of 34. Two apparent misses along the way were the
harness's: its type edit split at the first comma, so `tuple[int, int]` and `Union[None, int, str]`
became garbage. It now splits at the first comma outside brackets.

