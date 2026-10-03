# First run on a real repository

Plumbline had only ever been run on its own synthetic drift zoo. This records the first run
on a real project, **Ontolith** (the library Plumbline is built on): what was done, what it
showed, and what it cannot show.

## Method

`plumb ingest` over Ontolith's whole first-parent history, read-only, into a fresh knowledge
base outside the repository. Default path exclusions applied (tests, build output, vendored
code). Importers in use: the static code importer and the docstring importer, so the only
documentation signal is **docstrings**. There are no README, docs-page or CHANGELOG
importers yet.

| | |
|---|---|
| Commits ingested (first-parent) | 151 |
| Python files | 157 (the `src/` tree is 61) |
| Wall time | about 40 seconds |
| Documented slots (docstring claims) | 513 |

## First attempt: 7 findings, all false

The first run reported seven open contradictions, all of one kind ("a docstring documents a
parameter the signature lacks"). **None was real.** Each was a defect in Plumbline, and each is
now fixed and covered by a drift-zoo scenario:

1. **A stale view was left standing.** A method gained a decorator the importer cannot see
   through. The importer rightly stopped stating a signature, but the knowledge base kept the
   *old* signature from months earlier, so the projector called an existing parameter
   missing (4 of the 7). Fix: a fact the importer stops stating is now withdrawn (ADR-0004
   Amendment 2).
2. **The decorator rule was too blunt.** The decorator was a `functools.wraps` locking wrapper
   defined in the same file, which keeps the signature, but 44 methods of the core backend had
   lost theirs. Fix: same-file wrappers built with `@wraps` are recognised (ADR-0007
   Amendment 2).
3. **A `*concepts` parameter documented by its bare name** was called absent. Fix: a starred
   parameter exists under its bare name.

The synthetic zoo could not have found any of these. The first (stale state across time) is
the kind of bug that only appears when real history exercises the code in ways its authors
did not think of.

## After the fixes

| | |
|---|---|
| Open contradictions | 0 |
| Documented slots corroborated by the code | 441 |
| Documented slots the code cannot confirm | 72 |
| Symbol-key ownership conflicts (both reported, none hidden) | 2 |
| Files the importer could not analyse | 0 |

All 72 unconfirmed slots are the same by-design case: a `Raises:` entry where the function body
has no *direct* `raise` of that exception (it propagates from something the function calls).
Absence of a raise can never be proven, so the projector abstains rather than guess. Nothing
else abstained, and no symbol was unknown to the knowledge base.

The two ownership conflicts are both a package `__init__.py` doing `from . import migrations`,
which binds a name with the same key as the `migrations.py` module. The module won and the
loser was reported, as designed (ADR-0005).

## What this does and does not show

**It shows** that the pipeline runs on a real, non-trivial history without crashing, that it
is fast, that it finds nothing to report once its own bugs are fixed, and that where it does
speak (441 slots) the code agrees with the docs.

**It does not show recall.** Zero findings on a carefully documented project is plausible, but
it is equally what a tool that cannot see anything would report. There is no ground truth here
for the drift it might have *missed*. The honest next measurement is to inject known drift
into real code (change a default, rename a parameter, delete a documented function) and check
that every injection is found, and that nothing else is.

**It does not show precision on other projects.** One repository, one set of conventions.
The three defects above were all specific to how this codebase is written; a different
codebase will surface different ones.
