# Product Requirements Document: **Plumbline**

*Governed, bitemporal reconciliation between a codebase and the documentation that describes it. Built on Ontolith.*

| | |
|---|---|
| **Working name** | Plumbline *(a plumb line is the builder's tool for checking that something is true. CLI: `plumb`. Alternatives are in Appendix A.)* |
| **Document type** | Product Requirements Document (proposal) |
| **Status** | Draft v0.1, for team review |
| **Owner** | *[PM]* |
| **Substrate** | Ontolith `>=1.0,<2.0` (Apache-2.0), used as a library dependency |
| **Last updated** | 2026-09-29 |

> **Note on scope.** This is a decision document, not a brainstorm. Where there was a real fork in the road I picked a side and recorded the reasoning (§15). The numbers I'm least sure of (precision targets, performance budgets, trust weights) are marked as starting points to validate in M1. The modeling decisions in §7 are not starting points. They are the product's core, and changing them later is expensive.

---

## 1. TL;DR

Plumbline ingests a repository's **source code** and its **documentation** (docstrings, README and `docs/` Markdown, CHANGELOG, GitHub wiki) into an **Ontolith knowledge base**. Every documented statement that can be checked against code becomes a provenanced assertion: which file, which lines, which commit, which extractor, how confident. Plumbline then lets Ontolith's own conflict machinery do the detecting. Code changing over time is recorded as **temporal supersession**, which is expected and needs no review. Documentation disagreeing with code, or with other documentation, becomes a **contradiction**. A contradiction is flagged, excluded from "trusted" reads, and sent to a human. It is never silently overwritten and never auto-resolved.

The reconciliation loop is governed end to end. AI coding agents can read the verified state and **propose** doc fixes over MCP. They can never write directly, and every AI-authored fix lands as a reviewed pull request. Because the substrate is bitemporal, Plumbline can answer questions no docs tool can today: *"What did our docs claim about `Client.connect` when we shipped v2.3?"*, *"When did this README first become wrong, and which commit did it?"*, and *"Which of our three sources for this default value are stale?"*

The first release (1.0) is Python code plus Markdown/docstring/changelog/wiki docs, self-hosted, with GitHub as the review surface.

---

## 2. Problem and why now

### 2.1 The actual pain

Documentation drift is not a writing-quality problem. It is a **consistency problem between two artifacts that change at different speeds, with no mechanism linking them**:

- **Code changes are enforced; doc changes are not.** Tests fail when code breaks. Nothing fails when a README example stops compiling, when a docstring lists a parameter that was removed two releases ago, or when the wiki's config table shows last year's default.
- **The same fact lives in many places.** A default timeout appears in the function signature, its docstring, the README's configuration table, a wiki "tuning" page, and the changelog entry that changed it. A PR updates one or two of these. The rest go quietly stale, and nobody can say which copy is authoritative without reading the code.
- **Drift is invisible until it costs something.** It surfaces as a support ticket, a failed integration, a confused new hire, or an incident, usually long after the commit that caused it. At that point, *when* the doc went wrong and *who* changed what are archaeology.
- **Fixing docs is under-governed in the other direction too.** "Just regenerate the docs with an LLM" swaps stale-but-once-true text for fluent text that may never have been true. A hallucinated doc fix is worse than a stale one because it looks freshly verified.

### 2.2 Why now

1. **AI coding agents speed up drift.** Agents change code faster than humans and rarely touch the README, the wiki, or examples far from the diff. More code churn with the same doc discipline means more drift, faster.
2. **Agents now read docs as ground truth.** READMEs, `AGENTS.md`/`CLAUDE.md`-style context files, `llms.txt`, and API docs are fed straight into agent context. Stale docs used to confuse humans. Now they produce wrong code at machine speed. Doc correctness has become a code-correctness input.
3. **AI-written docs need provenance.** Teams already let agents write documentation. They have no way to tell which doc statements a human verified, which an agent produced, with which model, and whether anyone checked them against code.
4. **The substrate now exists.** Ontolith 1.0 provides the hard parts as tested primitives: append-only provenanced assertions, bitemporal `as_of`, temporality-routed conflict handling, a governed propose/review path, AI principals with accountable owners, sandboxed plugins, and an MCP surface with no direct-write tool. Before this, a product like Plumbline would have had to build all of that first.

### 2.3 Why existing tools don't solve it

| Category | Examples | What they do well | Why they don't close the gap |
|---|---|---|---|
| **Docstring/signature linters** | pydoclint, darglint, interrogate | Point-in-time checks that a docstring's param list matches its signature, in one file | Single source (docstring only); no README, wiki, or changelog; no cross-source agreement; no history; no provenance; no workflow beyond "CI red" |
| **Code-coupled docs platforms** | Swimm (auto-sync) | Detect when code snippets referenced by a doc change | Tracks *snippet* changes, not *claims*; doesn't reason about whether a statement is still true; no bitemporal record; proprietary doc store |
| **Docs platforms / AI writers** | Mintlify, GitBook, ReadMe, AI-generated repo wikis | Authoring, hosting, AI drafting | Generate or host docs. They don't verify claims against code, and AI output lands without governance or model provenance |
| **Generated API reference** | Sphinx autodoc, mkdocstrings, TypeDoc | Can't drift, because they are the code | Covers only what's derivable from code. Prose, READMEs, tutorials, wikis, and examples (where drift actually happens) are out of scope |
| **Prose/link linters** | Vale, markdown-link-check | Style and dead links | No notion of what a sentence claims about code |

**Plumbline's wedge** is the combination none of these have:

1. **Claims, not text.** The unit is a checkable statement ("`Client.connect` takes `timeout`, default `30`"), not a snippet or a page.
2. **Multi-source corroboration, surfaced explicitly.** Every source that makes a claim is recorded separately with its own provenance and confidence. Agreement and disagreement are both first-class and never averaged away.
3. **Honest conflict semantics.** "The code changed" (supersession) is different from "the docs are wrong" (contradiction), and the product treats them differently by construction.
4. **Time travel over docs and code together.** Every claim and every code fact is bitemporal, so audits, release retros, and "when did this go wrong" questions have exact answers.
5. **Governed AI participation.** Agents can read verified state and propose fixes. They cannot land anything unreviewed, and every AI contribution records its accountable human owner and model version.

---

## 3. Vision and product principles

1. **Drift is a contradiction, not a diff.** We don't compare file versions. We compare *what sources claim* about the same fact, and let governed conflict routing decide what's expected change and what's disagreement.
2. **The code is a witness, not a judge.** When docs and code disagree, Plumbline does not assume the docs are wrong. Sometimes the code regressed and the docs describe intended behavior. A human decides, and the decision is recorded.
3. **Precision over recall.** A drift tool that cries wolf gets muted within a week. Every v1 extractor is deterministic and abstains when unsure. We would rather miss drift than invent it.
4. **Nothing unreviewed from a model lands.** Any component that calls an LLM is an `ai` principal with an accountable owner, and its output always goes to human review. No exceptions, no trust-level escape hatch.
5. **Humans review where they already work.** In v1, GitHub pull requests and check runs are the review surface. We don't build a parallel review UI.
6. **History is never destroyed.** Retractions, supersessions, resolutions, and waivers are all append-only and queryable. "What did we believe on date X" always has an answer.
7. **Boring infrastructure.** One SQLite file per repository, one self-hosted process, standard Git and GitHub integration points.

---

## 4. Goals and non-goals

### 4.1 Goals (1.0)

- Ingest a Python codebase and its Markdown, docstring, changelog, and GitHub-wiki documentation into an Ontolith KB as provenanced, bitemporal assertions.
- Detect **drift** (doc-vs-code and doc-vs-doc disagreement on checkable facts) with **precision ≥ 90%** on deterministic extractors.
- Drive drift to resolution through a governed workflow: triage, dispositions, waivers, doc-fix proposals, and pull requests.
- Let AI coding agents query verified state and propose fixes over MCP, with no direct-write path.
- Answer time-travel and lineage questions about docs and code: `as-of <release>`, `blame <fact>`, `history <fact>`.
- Render reconciled output: a reference site with per-fact trust badges, a verified-only agent-context export, and a SARIF drift report for CI.
- Gate pull requests on drift they *introduce*, not on the pre-existing backlog.

### 4.2 Non-goals (1.0), decided

These are deliberate cuts, not oversights:

- **Not a docs authoring or hosting platform.** Authored prose stays in the repository. The repo is the source of truth for doc *text*; the KB is the source of truth for *reconciliation state*.
- **No behavioral-prose verification.** "This function retries on failure" is not checked in 1.0. Only structural and declarative facts with a deterministic code projection are reconciled (§7.4). LLM-assisted prose claim extraction ships as an **opt-in beta** and is always reviewed.
- **No code execution.** No doctest running, no importing user modules, no executing examples. All analysis is static. Executing untrusted repository code is a different security product.
- **No languages beyond Python** for code facts. TypeScript is the first post-1.0 language.
- **Single tracked branch per repository.** One tracked branch (usually `main`), linearized by first parent. Maintenance lines and backport branches are deferred.
- **One KB per repository.** Cross-repository queries are deferred. Ontolith's `Ontology` currently operates on a single namespace, and we don't want to fake federation.
- **No non-Git doc sources.** Confluence, Notion, and Google Docs are deferred. GitHub wikis are in scope because they are Git repositories.
- **No custom review web app.** Reviews happen in GitHub (check runs, PR comments, PRs) and the CLI. A read-only generated report site is the only web surface.
- **No hosted SaaS in 1.0.** Self-hosted only. A managed offering is a later, separable layer, mirroring Ontolith's open-core stance.
- **No auto-resolution, ever.** Not even for "obviously fixed" cases. Plumbline pre-computes a suggested winner, and a human confirms it.

---

## 5. Target users and personas

| Persona | Description | Primary jobs-to-be-done | What they touch |
|---|---|---|---|
| **Platform / DevEx lead** *(economic buyer)* | Owns docs quality and developer experience across a set of repositories | Know how much of our documentation is currently true; stop drift from shipping; show the trend | Drift dashboard/report, CI gate policy, waiver policy, metrics |
| **Maintainer / code owner** *(primary daily user)* | Owns a package or module and reviews changes to it | Get told precisely which doc statements my change broke; resolve disputes fast; don't get spammed | PR check runs, drift comments, one-click dispositions, `plumb explain` |
| **Individual OSS maintainer** | Solo or small team, limited time, many downstream users | Keep README/examples/changelog honest without a docs team; triage the backlog once, then only see new drift | CLI, GitHub Action, baseline triage |
| **Docs / technical writer** | Owns tutorials, guides, wiki | Know which pages have stale claims and what the code actually says now; prove what docs said at a release | Page-level drift report, `as-of`, doc-fix PRs |
| **AI coding agent** *(non-human principal)* | Operates semi-autonomously on the repo, e.g. a coding agent in CI or an IDE | Ground itself in *verified* facts; after changing code, propose the matching doc fixes; flag disagreements it notices | MCP tools (read, query, provenance, propose, flag), always as an `ai` principal with an owner |
| **Auditor / compliance reviewer** *(occasional)* | Needs evidence that published docs matched shipped behavior | Reconstruct what docs claimed at release X and who approved changes | `as-of`, provenance export, resolution trail |

**Primary adopters for 1.0:** Python library and platform teams (5 to 200 engineers) with public or internal API docs, and prominent Python OSS projects. We dogfood on Ontolith itself first. Its SPEC has explicit "Implementation deviations" notes, which are a real, labeled corpus of doc/code drift.

---

## 6. Core user journeys

### J1: First run and baseline triage *(maintainer, ~15 minutes to first report)*

1. `pipx install plumbline` → `plumb init` in the repo creates `plumbline.toml` and a KB file, registers principals, and applies the schema.
2. `plumb ingest --backfill 12mo` replays the last 12 months of first-parent history oldest-first (§7.7). Code facts, doc claims, and projections are written with valid-time equal to each commit's time.
3. `plumb drift` prints open contradictions grouped by page and by symbol, ranked (§7.6). Typical first run: a backlog of tens to hundreds of items.
4. The maintainer runs `plumb triage --baseline`. This walks the backlog in batches with a suggested disposition per item ("code is truth; 14 README claims stale"). The maintainer confirms in bulk. **Each confirmation is recorded as an individual, attributed `resolve_contradiction` by that human**, not as a bulk system action.
5. From then on the CI gate only fails on **newly introduced** drift.

### J2: A code change breaks the docs *(maintainer, in a PR)*

1. A PR changes `Client.connect(timeout=30)` to `Client.connect(timeout=60, *, retries=3)` and updates the docstring, but not the README or the wiki tuning page.
2. The Plumbline check run copies the main KB into a **shadow KB** for the PR head and ingests the diff there. The main KB is never touched by unmerged code.
3. In the shadow KB, `Symbol.param_default[timeout]` is **superseded** (code change, expected). The projection for Fact `py:acme.Client.connect#param.timeout.default` changes to `60`. The docstring's new claim `60` corroborates it. The README claim `30` and the wiki claim `30` **contradict** it.
4. The check run fails with two *introduced* contradictions. Each one links to the README and wiki lines (anchor URIs at the PR head SHA) and to the code line.
5. The author either fixes the README in the same PR (the shadow re-run shows the contradiction resolving to corroboration) or asks the agent (J3) to propose fixes. For the wiki, which lives in a different repository, a doc-fix PR against the wiki repo is opened and linked.
6. On merge, the main KB ingests the merged commit. Any contradictions that remain open enter the normal queue with the PR linked as the introducing change.

### J3: An AI agent proposes the doc fix *(agent + human reviewer)*

1. The coding agent (`ai` principal `coder-bot`, owner `alice@acme.com`) calls `plumb.drift_for_paths` over MCP and gets the two contradictions.
2. It reads the provenance and the current `DocSection.text` for the README section, then calls `plumb.propose_doc_fix` with new section text, a rationale, confidence `0.9`, and a source (the code anchor at the PR head SHA).
3. This becomes an Ontolith **proposal** on `DocSection.text`, authored by `coder-bot`, recording model and version, and `acting_as` if the agent was invoked on a human's behalf. Policy always returns `RequireReview` for `ai` authors.
4. Plumbline renders the proposal as a suggested change on the PR, or as a separate PR for out-of-repo sources like the wiki.
5. A human code owner approves. On merge, Plumbline records `accept_proposal` with that human as reviewer, re-ingests the section, and the new doc claim corroborates the code. If the owner closes the PR, the proposal is rejected with the close reason.
6. If the agent's proposed text itself contains a *new* wrong claim, the shadow-KB check on that PR catches it before merge. The agent can't grade its own homework.

### J4: "Is the code wrong, or the docs?" *(maintainer)*

1. A refactor changed `parse(strict=True)` to default `strict=False`. Docs across four sources say `True`.
2. The maintainer inspects the contradiction and decides the docs describe the *intended* contract and the refactor was a regression. They choose disposition **`code_defect`**. The doc claim wins, the code projection is retracted, and Plumbline proposes a **Waiver** linked to a new issue (§7.6).
3. The waiver suppresses re-raising for this exact code value. When the code is fixed, the projection matches the docs again and the waiver auto-expires on the next code change of that fact.

### J5: Time travel and blame *(writer / auditor)*

- `plumb as-of v2.3 --page docs/configuration.md` shows every claim that page made at the v2.3 release commit, with each claim's status *at that time* and what the code said then.
- `plumb blame py:acme.Client.connect#param.timeout.default` returns: the code changed at commit `a1b2c3` (2026-03-04), the README claim became contradicted at that point, the contradiction was detected at 2026-03-04T10:12Z, resolved by `bob@acme.com` on 2026-03-09 as `docs_stale`, and fixed by PR #812, proposed by `coder-bot` (model captured) and approved by `bob`.
- `plumb history <fact>` lists the full append-only trail across every source.

### J6: Grounding an agent in verified facts only *(agent, read path)*

An agent working in the repo queries Plumbline over MCP (`plumb.check_symbol`, or Ontolith's own `ontolith.query`). **Flagged claims are excluded by default** (Ontolith's `.include_flagged()` is opt-in), so the agent sees only undisputed, code-corroborated facts unless it explicitly asks for disputed ones. The exported `verified-context.md` artifact carries the same guarantee for agents that don't speak MCP.

---

## 7. How Plumbline maps onto Ontolith

This section is the heart of the product. Anyone implementing Plumbline should read it before writing code.

### 7.1 The central modeling decision: two layers, one rule

The obvious design, "doc claim and code fact share one predicate," breaks immediately. Ontolith routes conflicts **by predicate temporality, not by author**:

- If the shared predicate is `time_varying`, a stale README re-import that disagrees with the code would **supersede the code's value**. Staleness would silently overwrite truth, which is exactly what SPEC §10 exists to prevent.
- If the shared predicate is `static`, every legitimate code change would contradict the *previous code value*, and the review queue would fill with "the code changed" noise.

So Plumbline uses **two layers** and **one rule**:

> **The rule: code history lives on `time_varying` predicates; reconciliation lives on `static` predicates. Doc claims never touch a `time_varying` predicate.**

| Layer | Purpose | Temporality | Written by | Conflict outcome |
|---|---|---|---|---|
| **L1: Code facts** (`Symbol.*`) | Faithful history of what the code *was* at every commit | `time_varying` | Code importer only | Code changes **supersede** (window closed, successor linked). No review, because change is expected. |
| **L2: Reconciliation slots** (`Fact.value`) | The arena where every source (docs *and* a projection of current code) states what a checkable fact is | `static`, `cardinality="single"` | Doc importers, the drift projector, reviewed AI/human proposals | Same value → **corroboration** (all kept, confidence never merged). Different value → **contradiction**, flagged and routed to review. |

The **drift projector** (a deterministic Reasoner, §7.5) connects the layers. On each ingested commit it projects the *current* L1 value of each checkable aspect into the matching L2 slot. Drift is then just Ontolith's standard static routing: a doc claim and the code projection land on the same `(Fact, Fact.value)` with overlapping validity and different values.

Why not collapse L1 into L2's projections? Because keeping projections current means **retracting** the old projection when code changes (§7.7), and "retracted" means "no longer asserted", not "was true until time T". L1 keeps the semantically correct history (superseded windows with `valid_to` set), so `as_of(v2.3)` answers "what was the code" correctly. L2 keeps the dispute and resolution record. Each layer uses the Ontolith semantics that actually fit it.

### 7.2 What a documentation claim is, as an Ontolith assertion

A **doc claim** is one Ontolith assertion:

| Assertion field | Plumbline content | Example |
|---|---|---|
| `subject` | The **Fact** entity: one per `(symbol, aspect)`, natural key `<symbol_key>#<aspect>` | `py:acme.client.Client.connect#param.timeout.default` |
| `predicate` | Always `Fact.value` | `Fact.value` |
| `value` / `value_type` | The **canonical form** of what the source states (§7.4). Exact-equality comparison is the whole detection mechanism, so canonicalization is the contract. | `"30"` / `Text` |
| `author` | The **per-source-kind importer principal**, e.g. `plumb-readme`, `plumb-docstring`, `plumb-wiki`, `plumb-changelog` | `plumb-readme` |
| `source` | **Anchor URI**: repo, commit SHA, path, line range (§7.3) | `repo://acme/sdk@9f3e1c2/README.md#L88-L91` |
| `confidence` | The extractor's stated belief that **this source asserts this value** (extraction fidelity), *not* a belief that the fact is true | `0.95` for a structured docstring section; `0.7` for an inline mention |
| `rationale` | Extraction rule that fired | `"md.table:config-defaults row 'timeout'"` |
| `valid_from` | Commit time of the revision where the source began making this claim | commit `9f3e1c2` time |
| `asserted_at` | Set by Ontolith's clock at ingest. Live mode: ingest time. Backfill: replay clock (§7.7). | |
| `model` | Only for AI-authored claims (beta extractor, agents) | `"claude-…/2026-xx"` |
| `metadata` | `extractor`, `extractor_version`, `claim_fingerprint`, `section_id`, `ingested_at` (wall clock, always real), `commit_author` (Git identity, informational) | |

Two decisions embedded here:

- **Git committers are not Ontolith principals.** The *author* of an imported claim is the importer principal, because the importer is what made the assertion. The Git author is recorded in `metadata` and in the anchor's commit. Making every committer a principal would mean identity sprawl with no authentication behind it. Humans become principals only when they *act in Plumbline*: reviewing, resolving, proposing, waiving. Those humans authenticate via GitHub or OIDC and map to Ontolith human principals.
- **One importer principal per source kind.** This gives provenance-level answers to "which *kind* of source is stale," supports per-source authority ranking (§7.6), and lets a whole source class be disabled or distrusted without touching the others.

### 7.3 Anchor URIs (provenance you can click)

```
repo://<owner>/<repo>@<commit_sha>/<path>#L<start>-L<end>            # file in the main repo
repo://<owner>/<repo>@<commit_sha>/<path>#sym=<qualname>             # docstring of a symbol
wiki://<owner>/<repo>@<wiki_commit_sha>/<page>#L<start>-L<end>        # GitHub wiki (git-backed)
```

Anchors are **immutable** because they pin a SHA. That matters: provenance must keep pointing at the exact text that made the claim even after the file changes. The UI and CLI also resolve the anchor to the current location of the same text when one exists.

### 7.4 What a "checkable fact" is: the 1.0 aspect catalog

Ontolith's static routing contradicts on **any** value difference. That makes the aspect catalog and its canonical forms the product's precision engine. Aspects are **atomic**, because docs rarely state whole signatures: a README example states "there's a `timeout` kwarg," not the full parameter list. One aspect per fact means partial claims hit exactly the slot they speak to.

| Aspect (suffix after `#`) | Value / canonical form | Code projection (from L1) | Doc sources that produce claims | Drift-capable? |
|---|---|---|---|---|
| `exists` | `Boolean` | Symbol table from static AST; **abstains** in modules with `__getattr__`, `*`-exports it can't resolve, or dynamic registration | Backticked qualified names, imports/calls in fenced Python blocks, docstring cross-refs, changelog "added/removed X" | Yes |
| `param_names` | canonical JSON list in declaration order, excluding `self`/`cls`, `*args`/`**kwargs` rendered as `*name`/`**name` | Signature | Docstring `Args:`/`Parameters` sections (Google, NumPy, Sphinx) | Yes |
| `param.<p>.exists` | `Boolean` | Signature (`true`/`false`); **abstains** if the signature has `**kwargs` | Keyword arguments in fenced-code calls, README parameter tables | Yes |
| `param.<p>.default` | canonical literal (`repr` of `ast.literal_eval`-able value; non-literal defaults → projector abstains) | Signature | Docstring "defaults to X", README/wiki parameter tables, Sphinx `:param ... default:` | Yes |
| `param.<p>.type` | canonical annotation string (PEP 604 unions, sorted members, `typing.` aliases normalized) | Annotations only (no inference) | Docstring types | Yes |
| `returns.type` | canonical annotation | Return annotation | Docstring `Returns:` | Yes |
| `raises.<Exc>` | `Boolean` | Direct `raise Exc` in body → `true`; **never projects `false`** (it can't prove absence) | Docstring `Raises:` | **Corroboration only.** Earns a "verified" badge, never produces drift (§14, R3) |
| `deprecated` | `Boolean` | `@deprecated`, `warnings.warn(..., DeprecationWarning)` at function entry | Deprecation admonitions, `.. deprecated::`, changelog "Deprecated" section | Yes |
| `added_in` / `removed_in` | version string (PEP 440 normalized) | **Lineage reasoner** over L1 history and `Release` entities | Changelog entries (Keep-a-Changelog), `.. versionadded::`/`versionchanged` | Yes |
| `cli.<cmd>.flag.<f>.exists` | `Boolean` | Static parse of `argparse`, `click`, and `typer` declarations | Shell blocks in Markdown (`$ tool --flag`), CLI reference tables | Yes |
| `env.<VAR>.exists` | `Boolean` | Literal `os.environ[...]`, `os.getenv(...)` keys | Env-var tables, prose in backticks with an `ENV_` style pattern | Yes |
| `project.version`, `project.requires_python` | Text (PEP 440 / specifier canonical) | `pyproject.toml` | README install sections, badges (static text), docs index | Yes |

**Abstention is a first-class projector output.** When the projector can't determine a value with certainty, it writes **nothing** to the L2 slot. A doc claim with no code projection stays *unverified*. It is not flagged, it doesn't count as drift, and it shows as "unverified" in reports. This is the single most important precision lever.

**Out of 1.0 (behavioral claims):** "returns `None` when the key is missing," "thread-safe," "retries three times." These have no deterministic projection, and exact-equality comparison of paraphrased prose would be meaningless. Section 10 (M3 beta) covers how they enter later without breaking the model.

### 7.5 Schema sketch (Ontolith class DSL)

```python
from ontolith import Concept, Property, Relation, Text, Boolean, DateTime, Ref

class Release(Concept):                    # natural_key: version, e.g. "2.3.0"
    tag: Text                              # static
    commit_sha: Text                       # static — a tag pointing elsewhere later is a new Release, not an edit
    released_at: DateTime                  # static

class Symbol(Concept):                     # natural_key: "py:acme.client.Client.connect"
    kind: Text                             # static: function|method|class|module|cli_command|env_var|project
    # --- L1: code history. All time_varying: code changing is expected. ---
    defined_at: Text = Property(temporality="time_varying")             # anchor of current definition (moves on refactor)
    signature_json: Text = Property(temporality="time_varying")         # full canonical signature, for history/as_of
    is_deprecated: Boolean = Property(temporality="time_varying")
    present: Boolean = Property(temporality="time_varying")             # false after deletion; window closes, history kept

class Fact(Concept):                       # natural_key: "<symbol_key>#<aspect>"
    about: Ref["Symbol"] = Relation()      # static
    aspect: Text                           # static
    # --- L2: the reconciliation slot. static + single: disagreement => contradiction. ---
    value: Text                            # static (default) — THE drift detector

class DocSource(Concept):                  # natural_key: "readme:README.md", "wiki:Tuning", "docstring:<module>"
    kind: Text                             # static: readme|docs|docstring|changelog|wiki|adr
    path: Text = Property(temporality="time_varying")                   # files get renamed

class DocSection(Concept):                 # natural_key: "<doc_source_key>::<stable heading path or symbol>"
    in_source: Ref["DocSource"] = Relation()                            # static
    text: Text = Property(temporality="time_varying")                   # doc edits supersede; enables as_of rendering
    mentions: Ref["Fact"] = Relation(cardinality="many")                # static+many: coexist, no dispute

class Waiver(Concept):                     # human-authored, always via reviewed proposal
    fact: Ref["Fact"] = Relation()         # static
    disposition: Text                      # static: code_defect|intentional_simplification|extraction_error
    suppressed_value: Text                 # static: the exact canonical value not to re-raise
    issue_url: Text | None = None          # static
```

(`Property(temporality=...)` for literal fields and `Relation(...)` for `Ref` fields are the actual Ontolith 1.0 DSL forms. Both default to `static`/`single`.)

Why each temporality is what it is:

- `Symbol.signature_json`, `present`, `is_deprecated`, `defined_at` are **`time_varying`**. They are the record of the code evolving. A new signature at commit C2 supersedes C1's, closing C1's window at C2's time. `kb.as_of(<v2.3 time>)` returns the v2.3 signature.
- `Fact.value` is **`static`, single-valued**, and deliberately so: at any instant a fact has one true value, and two sources stating different values *is* a disagreement.
- `DocSection.text` is **`time_varying`**. Editing a doc is an expected change, and we want `as_of` rendering of historical docs. Doc *text* never participates in drift directly. Only the claims extracted from it do.
- `DocSection.mentions` is **`static` with `cardinality="many"`**. A section mentioning many facts is legitimately multi-valued (ADR-0017), so it coexists and never disputes.
- `Release.commit_sha` is **`static`**. If a tag is moved, that is a real disagreement worth surfacing, not an expected change.
- `Waiver.*` is **`static`**. A waiver is a decision. Changing it means a new waiver.

### 7.6 Governance: principals, capabilities, policy, resolution

**Principals (per repository KB):**

| Principal | Kind | Capability | How it writes | Notes |
|---|---|---|---|---|
| `plumb-code` (code importer) | `service` (plugin) | `write` | `propose` via `WriteView` → auto-accepted | Only writer of L1 `Symbol.*` |
| `plumb-docstring`, `plumb-readme`, `plumb-docs`, `plumb-changelog`, `plumb-wiki` | `service` (plugins) | `write` | `propose` via `WriteView` → auto-accepted | Importing *what a source says* is observation, not editorializing, so it auto-lands. Disagreement is what gets reviewed. |
| `plumb-projector`, `plumb-lineage` (reasoners) | `service` (plugins) | `write` | `propose`/`retract` via `WriteView` | Deterministic, with no model calls |
| AI agents (`coder-bot`, `plumb-extractor-llm` beta) | **`ai`** with a required `owner` | `propose` | MCP / SDK `propose` | **Always `RequireReview`**, with `model` captured per assertion |
| Maintainers / code owners | `human` | `review` | Resolve, accept/reject, waive | Mapped from GitHub identity (verified email) or OIDC |
| Platform admins | `human` | `admin` | Schema, principals, plugin registration, policy | |

**Rule: anything that calls a language model is an `ai` principal and never a registered plugin.** `PluginRegistry.register()` creates `service`-kind principals, and a `service` with `write` auto-accepts under `ThresholdPolicy`. An LLM-backed Reasoner plugin would therefore let model output auto-land, violating Ontolith's AI-review invariant through a side door. All LLM-backed components in Plumbline run as external clients that authenticate as `ai` principals and go through `propose`.

**Default policy (pure, deterministic, composed from Ontolith 1.0 built-ins):**

```
Composite(all=[
    RequireReviewForAI(...),          # ai authors => RequireReview (reviewers: owner), no escape via trust or delegation
    ThresholdPolicy-equivalent gate,  # service/human with write+ => auto-accept; propose => review
    RequireReviewByRole({             # route reviews to CODEOWNERS of the touched paths
        "path:src/acme/client/**": ["bob@acme.com", ...], ...
    }),
])
```

`CODEOWNERS` is compiled into the `RequireReviewByRole` mapping **at configuration time**, and a config reload creates a new policy instance. The policy itself does no I/O, keeping Ontolith's policy-purity contract (SPEC §9.2).

**Resolution and dispositions.** Ontolith resolves a contradiction by choosing one winning member. The rest are retracted, and the resolver must be a non-AI `review`-capable principal who is not a party to any member. Plumbline adds a **disposition**, recorded in the contradiction's rationale history and mirrored into a `Waiver` where applicable:

| Disposition | Winner | Follow-up Plumbline does |
|---|---|---|
| `docs_stale` *(most common)* | The code projection | Opens or links doc-fix proposals for each stale claim's `DocSection`. After resolution, runs a **re-affirm pass**: current doc claims matching the winner are re-asserted and activate as corroboration (see R4). |
| `code_defect` | The doc claim | Proposes a `Waiver` (suppressing re-projection of that exact code value) with a linked issue. The waiver expires automatically when L1 supersedes that code fact again. |
| `doc_vs_doc` | Whichever doc claim matches code (or the code projection) | Same as `docs_stale`, only for the losing sources |
| `extraction_error` | The code projection | Retracts the bad claim and records its `claim_fingerprint` in a suppression list so re-import doesn't re-extract it. **Counts against extractor precision** (§11). |
| `intentional_simplification` | The code projection, or none | A `Waiver` for "the docs intentionally omit or simplify this." Reported separately so it doesn't hide real drift. |

**Why no auto-resolution, even when a later commit fixed the docs:** the resolver *is* the accountable human in provenance. A service-principal resolver would launder that accountability. The one "near-automatic" path: when a **Plumbline-opened doc-fix PR** (already linked to the contradiction) is approved and merged, the approving human is recorded as resolver, because approving that PR was explicitly the resolution act. For any other fix, Plumbline pre-computes the suggested winner and a human confirms with one click. Ontolith's party rule gives us a free two-person rule: a human who delegated an agent's doc-fix proposal (`acting_as`) is a party to it and cannot also resolve it.

**Ranking the review queue.** SPEC §10.3 says rank by confidence × source trust. `PluginRegistry` creates plugin principals at `trust_level=0`, so native per-principal trust can't distinguish source kinds today. 1.0 therefore ranks with a **product-level authority map** keyed by author principal (defaults: code projection 1.0, docstring 0.9, docs 0.8, readme 0.8, changelog 0.7, wiki 0.5, AI-extracted 0.4). Score: `max over non-code members of (confidence × authority)` × `page traffic weight` (when analytics are wired in). This is for **ranking only**. It never combines confidences into a stored value. (Upstream ask U2: let `register()` accept a `trust_level` so `.trust_at_least()` works natively.)

### 7.7 Ingestion protocol and time semantics

**Commit-apply protocol.** Each commit on the tracked branch is applied in a fixed order, so transient intermediate states never create false contradictions:

1. **L1:** the code importer writes changed `Symbol.*` facts (supersession closes the old windows).
2. **Projection retract:** the projector retracts its L2 projections whose underlying L1 fact changed or became undeterminable. (Projections are "the code currently says X." Once that stops being true, the projection is withdrawn. L1 holds the history.)
3. **Claim retract:** doc importers retract claims whose source no longer makes them (section edited or deleted).
4. **Projection assert:** the projector writes the new projections.
5. **Claim assert:** doc importers write new or changed claims.
6. **Reconcile hooks:** re-affirm passes, waiver expiry, and the suggested-winner computation.

Importers **diff against the KB's current active state**. An unchanged fact or claim produces no write, so KB growth is proportional to *churn*, not repository size × commits.

Note on step 3: retracting a claim that is currently a flagged member of an open contradiction requires `review` capability (ADR-0030). An importer's retraction there is routed to review rather than applied. That is correct behavior: the doc changed while under dispute, and the human resolving the dispute should see it. The suggested-winner logic accounts for it.

**Valid time vs. assertion time.**

| Dimension | For code facts and in-repo doc claims | For GitHub wiki claims |
|---|---|---|
| `valid_from` | Time the commit landed on the tracked branch (committer time, clamped to be monotonic along first parent) | Wiki commit time |
| `asserted_at` | **Live mode:** ingest time (seconds after push). **Backfill:** the replay clock pins it to the commit's time (below). | Same |
| `metadata.ingested_at` | Always the real wall-clock ingest time | Same |

**Backfill uses a replay clock (decided).** Ontolith's `as_of(t)` requires *both* `valid_from ≤ t` and `asserted_at ≤ t`. If backfilled history were asserted at today's time, `as_of(v2.3)` would return nothing, which kills the headline feature. Plumbline therefore injects a deterministic `Clock` during backfill that returns each commit's time. We treat the repository's history as the transaction log the KB is reconstructing, so "when did we learn this" means "when did it become knowable in the repo." That is also the answer users want from `blame`: *when drift was introduced*. The real ingest time is kept in `metadata.ingested_at` so the substitution is auditable, never hidden. Constraints: backfill happens only at onboarding, into a fresh KB, strictly oldest-first, before any live writes. A deeper backfill later means a rebuild with a human-decision replay (see R6).

**Shadow KBs for pull requests.** PR checks copy the main KB file (SQLite, one file) and ingest the PR's commits into the copy. The copy is discarded after the check. Unmerged code never enters the main KB's history, and the PR check reports exactly the contradictions **introduced** by the PR (the set difference of open contradictions, shadow vs. main).

### 7.8 Plugin mapping (and the mappings that looked right but aren't)

| Ontolith protocol | Plumbline component | Given | Notes |
|---|---|---|---|
| **Importer** | `python-code-importer` (L1), `docstring-claim-importer`, `markdown-claim-importer`, `changelog-claim-importer`, `wiki-claim-importer` | `WriteView` + a **bytes payload** | **Parsers never touch the filesystem or network.** The host reads the Git objects and hands the importer `{path: bytes}` plus commit metadata as the picklable `source` argument. Every importer's manifest is `network=False, filesystem=False`, which on Linux is enforced by seccomp inside Ontolith's process sandbox. This matters because Plumbline parses **untrusted repository content** (hostile Markdown or Python aimed at a parser bug). It also sidesteps KI-106 (a filesystem-capable plugin could reach the KB file directly). |
| **Reasoner** | `drift-projector` (L1 → L2), `lineage-reasoner` (`added_in`/`removed_in` from L1 history plus `Release`) | `WriteView` | Deterministic only. Uses `assertions()`/`get_entity()`/`schema()`, which are proxied across the sandbox; `query()`/`as_of()` are not yet available inside isolated plugins (Ontolith KI-101), so the reasoners are designed around flat `assertions()` reads. |
| **Validator** | `CanonicalValueValidator`, `AnchorValidator`, `AspectCatalogValidator` | `ValidatorKbView` | Registered on the `Ontology` directly (ADR-0029 `validators=`), so they run at **every** commit point, including `accept_proposal` of a reviewed AI proposal. They **reject** non-canonical values (the main defense against spurious contradictions from agents or buggy extractors), claims without a resolvable anchor, and unknown aspects. |
| **Exporter** | `mkdocs-reference-exporter`, `verified-context-exporter`, `sarif-drift-exporter`, `json-snapshot-exporter` | `ReadOnlyView` | See §8.5 |
| **Connector** | *none in 1.0* | | See the GitHub note below |

**Two intuitive mappings that are wrong on Ontolith, so we don't use them:**

1. **"A Validator flags stale doc claims as contradictions."** An Ontolith Validator can only *reject* a write (it returns violation messages, and the write aborts). It receives a read-only view and has no path to open a contradiction. Plumbline doesn't need one: **drift detection is structural.** It emerges from static conflict routing when the projector's value and a doc claim collide on one slot. Validators guard the *inputs* to that routing.
2. **"GitHub sync is a Connector."** A Connector's `WriteView` can propose and retract but cannot accept, reject, or resolve, and that is correct, because those are human review acts. The GitHub integration *does* perform review acts (recording a human's PR approval as `accept_proposal` or `resolve_contradiction` by that human), so it runs as **trusted host code in the Plumbline server** using the SDK with the mapped human principal, not as a sandboxed plugin. Reserving the Connector protocol for pure data sync (Confluence and Notion, post-1.0) keeps that boundary honest.

---

## 8. Functional requirements

Priorities: **P0** = required for 1.0, **P1** = 1.0 if on schedule, otherwise 1.1, **Beta** = ships behind a flag in 1.0.

### 8.1 Ingestion

| ID | Requirement | Pri |
|---|---|---|
| ING-1 | Ingest a Python codebase into L1 `Symbol.*` facts using static AST analysis only. No import or execution of user code. | P0 |
| ING-2 | Extract doc claims from docstrings (Google, NumPy, Sphinx field lists), Markdown (`README*`, `docs/**`, fenced `python`/`pycon`/`shell` blocks, pipe tables with recognized headers, backticked qualified names), `CHANGELOG` (Keep-a-Changelog), and Sphinx directives (`versionadded`, `deprecated`) embedded in Markdown/MyST. | P0 |
| ING-3 | Ingest GitHub wikis as a second Git source with its own anchors and importer principal. | P1 |
| ING-4 | Record ADRs as `DocSource`/`DocSection` (for search and time travel) **without claim extraction** by default. ADRs are historical records by design; extracting "we use X" from a superseded ADR would be manufactured drift. Opt-in: structured front-matter `facts:` blocks only. | P0 |
| ING-5 | Canonicalize every value to the aspect catalog's canonical form (§7.4), with a versioned canonicalizer. A canonicalizer version bump triggers a re-projection pass. | P0 |
| ING-6 | Symbol resolution: resolve doc references (`connect`, `Client.connect`, `acme.Client.connect`) to qualified symbol keys using the module import graph and re-exports. Unqualified ambiguous references produce **no claim** (abstain) and are counted in an "ambiguous references" coverage stat. | P0 |
| ING-7 | Live mode: ingest each push to the tracked branch using the commit-apply protocol (§7.7), idempotently (re-ingesting a commit is a no-op). | P0 |
| ING-8 | Backfill mode: replay N months of first-parent history oldest-first with the replay clock, into a fresh KB only. | P0 |
| ING-9 | Release awareness: create `Release` entities from tags matching a configurable pattern on the tracked branch's first-parent history. | P0 |
| ING-10 | Per-path include/exclude and per-source-kind enable/disable in `plumbline.toml`. | P0 |
| ING-11 | Never store function bodies or arbitrary source code in the KB. Only derived facts, anchors, and doc text. | P0 |

### 8.2 Drift detection

| ID | Requirement | Pri |
|---|---|---|
| DRF-1 | Drift detection **is** Ontolith static conflict routing on `Fact.value`. No parallel diffing engine. Any "drift" Plumbline reports must correspond 1:1 to an Ontolith contradiction or to an explicit "unverified" state. | P0 |
| DRF-2 | Drift projector projects every drift-capable aspect (§7.4) for every symbol that has at least one doc claim or mention. Facts no doc mentions are not projected (keeps the KB proportional to documented surface). | P0 |
| DRF-3 | Projector abstention: never assert a value the analysis can't determine. Never project `false` for `exists` in dynamic modules or `param.<p>.exists` when `**kwargs` is present. | P0 |
| DRF-4 | Classify each open contradiction as `doc_vs_code`, `doc_vs_doc`, or `doc_vs_doc_vs_code` based on member authors. Attach the **introducing commit** (the commit whose apply opened it). | P0 |
| DRF-5 | "Undocumented" and "unverified" are **not** drift. Report them as coverage metrics in separate sections. | P0 |
| DRF-6 | Rename hinting: when `exists` flips to `false` for a symbol and a new symbol with a matching signature appears in the same commit, attach "likely renamed to X" to the suggested fix. It is a hint only and never auto-applied. | P1 |
| DRF-7 | Waiver and suppression checks: the projector skips re-projection of a value covered by an active `Waiver`, and importers skip claims whose fingerprint is on the extraction-error suppression list. | P0 |

### 8.3 Reconciliation workflow

| ID | Requirement | Pri |
|---|---|---|
| REC-1 | Resolve a contradiction with a disposition (§7.6) via CLI (`plumb resolve`) and via GitHub (PR comment command or check-run action). Every resolution is an Ontolith `resolve_contradiction` by the mapped human principal. | P0 |
| REC-2 | Suggested winner and disposition for each contradiction, with the evidence behind the suggestion (code anchor, agreeing sources, disagreeing sources, introducing commit). | P0 |
| REC-3 | Baseline triage (`plumb triage --baseline`): batch confirmation of suggestions for the onboarding backlog, still one attributed resolution per contradiction. | P0 |
| REC-4 | Doc-fix proposals: humans or AI principals propose new `DocSection.text`. Plumbline renders the proposal as a PR (or as a suggested change on an existing PR). PR merge by a review-capable human → `accept_proposal` with that reviewer. PR close → `reject_proposal` with the reason. Requested changes on the PR → `request_changes`; a new push → `resubmit`. | P0 |
| REC-5 | Re-affirm pass after resolution (§7.6, R4). | P0 |
| REC-6 | Waivers: create via reviewed proposal, list, and expire (automatically on the next L1 change of the underlying fact, or at a configured date). | P0 |
| REC-7 | CI gate: `plumb check` exits non-zero only on **introduced** drift above a configured severity. It emits SARIF for GitHub code scanning and a check run with inline annotations at the doc lines. | P0 |
| REC-8 | Notifications: a per-owner digest of their open drift (GitHub issue comment or email via webhook). No real-time pings in 1.0. | P1 |

### 8.4 Query and time travel

| ID | Requirement | Pri |
|---|---|---|
| QRY-1 | `plumb explain <fact|symbol|path:line>`: every claim, its provenance (one Ontolith `provenance()` call per assertion), corroboration list, and current status. | P0 |
| QRY-2 | `plumb as-of <release|sha|datetime>`: KB state via Ontolith `as_of`, optionally scoped to a page or symbol, including what the code said at that time (L1) and what the docs claimed (L2), each with its status *at that time*. | P0 |
| QRY-3 | `plumb blame <fact>`: introducing commit, detection time, resolution (who, when, disposition), and fix PR. | P0 |
| QRY-4 | `plumb history <fact|section>`: full append-only trail including superseded, retracted, and flagged records (`include_history`, `include_flagged`). | P0 |
| QRY-5 | Corroboration view: for any fact, the sources that agree with the code, the sources that disagree, and the sources that are unverified. Confidences are shown per source and never combined. | P0 |
| QRY-6 | Semantic search over `DocSection.text` ("where do we talk about retries?") using Ontolith hybrid query with a real `Embedder` (a local sentence-embedding model by default; Ontolith's default hashing embedder is not semantic). | P1 |
| QRY-7 | Default reads exclude flagged assertions. Every trusted surface (exports, MCP `check_symbol`) shows **only undisputed** facts unless the caller opts in. | P0 |

### 8.5 Output and rendering (Exporters)

| ID | Requirement | Pri |
|---|---|---|
| OUT-1 | **Reconciled reference site** (MkDocs): per-symbol pages generated from L1 plus reconciled L2 facts, each fact with a trust badge: *verified* (code-corroborated), *unverified*, *disputed* (with a link to the open contradiction), *waived*. Authored prose pages are rendered as they are in the repo (from accepted `DocSection.text`) with a banner listing any open drift on the page. | P0 |
| OUT-2 | **Verified agent context** (`verified-context.md` / `llms.txt`-style): only code-corroborated, undisputed facts, each carrying an anchor. Regenerated on each ingest. This is the "safe to feed an agent" artifact. | P0 |
| OUT-3 | **SARIF drift report** and a machine-readable JSON snapshot. | P0 |
| OUT-4 | **Historical render**: `plumb export --as-of v2.3` renders the reference site as it would have been at that release, with that release's trust state. | P1 |

Plumbline **does not** rewrite authored doc files directly. Changes to authored prose always go through a doc-fix proposal and a PR (REC-4). Exporters write only to generated-output locations.

### 8.6 Agent integration (MCP)

| ID | Requirement | Pri |
|---|---|---|
| AGT-1 | Ship a **Plumbline MCP façade** with task-shaped tools, each implemented as a composition of governed Ontolith calls: `plumb.check_symbol` (read), `plumb.drift_for_paths` (read), `plumb.explain` (read, provenance), `plumb.as_of` (read), `plumb.propose_doc_fix` (propose on `DocSection.text`), `plumb.flag_disagreement` (wraps `flag_contradiction`; needs two existing assertions on the same fact slot). | P0 |
| AGT-2 | **No direct-write tool, verified by a closed-set test.** The façade's tool list must equal an allow-list exactly. A subset check is not enough (lesson from Ontolith KI-085). No tool may call `assert_literal`, `accept_proposal`, `resolve_contradiction`, or any waiver-creating path. | P0 |
| AGT-3 | Agents authenticate as `ai` principals with a required owner and a token (Ontolith ADR-0014). Every proposal records `model` and, when invoked for a human, `acting_as`. | P0 |
| AGT-4 | `propose_doc_fix` validates at the edge (canonical anchors, section exists, text size limits) and returns the proposal id plus the shadow-KB drift delta its text would produce, so the agent can see whether its own fix introduces new drift before a human looks. | P0 |
| AGT-5 | Also expose Ontolith's own MCP server read tools against the Plumbline KB, for agents that want raw query access. | P1 |
| AGT-6 | **Beta:** `plumb-extractor-llm`, an opt-in `ai` principal that proposes canonical claims extracted from prose (for example "timeout defaults to 30 seconds" becomes `param.timeout.default = "30"`). Every extracted claim goes to review. Accepted claims then take part in normal static routing. | Beta |

---

## 9. Non-functional requirements

### 9.1 Performance (starting points, validated in M1, enforced by 1.0)

Reference repository: ~200k LOC Python, ~10k symbols, ~500 doc pages, ~150k assertions after onboarding. Hardware: 4-vCPU Linux CI runner or laptop.

| Operation | Budget (p95) | Basis |
|---|---|---|
| Live ingest of a typical push (≤ 50 changed files) | < 60 s end to end | Diff-based, churn-proportional writes; Ontolith `propose` + commit budget p95 < 50 ms per write, typically far less uncontended |
| PR shadow-KB check | < 3 min, including KB copy | One SQLite file copy plus incremental ingest |
| Initial ingest, no history | < 15 min | ~150k governed writes plus parsing |
| Backfill, 12 months (~3k commits) | < 2 h, resumable | Replay is sequential by design |
| `plumb explain` for a fact | < 200 ms | Ontolith single-entity get with provenance, p95 < 10 ms per assertion |
| `plumb as-of` for one page | < 1 s | Ontolith `as_of` reconstruction p95 < 300 ms at 100k assertions |
| Exporter full site render | < 5 min | |

Known substrate constraints we design around:

- **Contradiction size.** Extending an open contradiction costs O(members) per write (Ontolith KI-100). Plumbline bounds members by allowing **at most one active claim per (DocSource, Fact)**, so members ≤ distinct sources. It alerts on any contradiction above 25 members.
- **Isolated plugin calls have no timeout** (Ontolith KI-102). The Plumbline orchestrator enforces its own per-call watchdog and fails the ingest of that commit, not the whole run, if a parser hangs on hostile input.
- **Semantic ranking is not bitemporal** (one embedding per entity, current only). `as-of` queries use symbolic filters. Semantic search is a present-tense feature in 1.0.

### 9.2 Security and governance posture

Mirrors Ontolith's own posture, applied to a product that parses untrusted content and invites AI agents in:

- **No direct-write path for any AI principal, anywhere.** MCP façade, SDK wrappers, and GitHub commands all route AI input through `propose`. Policy forces review for `ai` authors, `resolve_contradiction` rejects AI resolvers, and the façade is closed-set tested (AGT-2).
- **LLM-calling code is never a plugin** (§7.6). It is always an `ai` principal with an owner, external to the KB process.
- **Untrusted-input parsing is sandboxed.** Importers run in Ontolith's per-call child process with `network=False, filesystem=False` and receive bytes only. **The supported production platform is Linux**, where these flags are enforced at the syscall level (seccomp). On macOS and Windows the process boundary is the only enforcement, and Plumbline logs the degraded mode loudly, as Ontolith does. Production deployments set `require_enforcement=True`. Ontolith's known residual gaps in its isolation floor (KI-110, KI-111) are inherited and tracked, not claimed away.
- **No code execution.** Static analysis only (non-goal §4.2).
- **Data minimization.** No function bodies in the KB (ING-11). Doc text is stored because it is already published or in-repo. Secrets scanning runs on doc text before storage; matches are redacted and the claim abstains.
- **Model egress is opt-in.** Features that send content to a model provider (agent fixes, beta extractor) are off by default, configurable per path, and support self-hosted models. Every call records `model` in provenance.
- **Identity mapping.** GitHub users map to human principals only via verified email or an explicit admin mapping. An unmapped GitHub user's approval is **not** recorded as a review act. The PR is marked "approval not attributable" and needs a mapped reviewer.
- **Audit.** Everything Plumbline writes is an Ontolith assertion, proposal event, contradiction event, or admin event: append-only and attributable. Plumbline keeps no mutable side database for decisions. Its only state outside the KB is configuration, caches, and the shadow-KB scratch space.

### 9.3 Deployment

- **1.0 is self-hosted only.** `plumb serve` is a single process exposing webhooks (GitHub App), the MCP façade, and the report site. It holds one SQLite KB per repository (Ontolith's default backend, WAL mode).
- **The KB is state, not cache.** It holds human decisions (resolutions, waivers, reviews) that **cannot be rebuilt from Git**. The KB directory must be backed up. `plumb backup` produces consistent snapshots, and we document this prominently.
- **CLI-only mode** (no server) is supported for individual maintainers: the KB lives in a persistent path the maintainer controls, and the GitHub Action runs `plumb check` against it via a cached artifact. Resolutions happen from the CLI.
- **Hosted SaaS:** post-1.0, as a separable layer (open-core, as with Ontolith). The managed-only candidates are multi-repo dashboards, SSO, and hosted model endpoints.
- **Storage format upgrades** ride on Ontolith's `db migrate` (ADR-0052). Plumbline's own schema evolves via Ontolith schema migrations. Changing any predicate's temporality is a breaking migration and needs an ADR.

### 9.4 Determinism and testability

- Every Plumbline component that writes to the KB gets an injected `Clock` and `IdProvider`, so ingestion of a fixed repository history is **byte-for-byte reproducible**. This is the basis of the golden-repo test suite (the "drift zoo," §10 M0).
- Policy is pure (Ontolith contract).
- The canonicalizer and every extractor carry a version in claim metadata. Upgrading one is a visible, auditable event.

### 9.5 Licensing

Apache-2.0, matching Ontolith, since the core value is embeddability in a team's CI. Trademark on the name.

---

## 10. Phased roadmap

Each milestone ends in a demonstrable, testable state. Durations assume a team of three engineers plus a half-time PM/designer.

### M0: Foundations *(~4 weeks)*

- Schema v1 (§7.5) applied to an Ontolith KB. ADRs for: the two-layer rule, the aspect catalog v1, the canonical forms spec, the anchor URI scheme, the replay clock, and "LLM-calling components are `ai` principals, never plugins."
- Canonicalizer library, versioned, property-tested (idempotent, order-insensitive where specified).
- Principal bootstrap (`plumb init`), plugin registration with sandboxing, validators wired via `Ontology(validators=…)`.
- **The drift zoo:** a synthetic Git repository with ~80 **seeded, labeled** scenarios (signature change with and without doc update, default change across four sources, rename, deprecation, removed symbol still in README, changelog wrong about version, dynamic-module abstention, `**kwargs` abstention, `code_defect` case, ADR superseded, and more), with the expected supersessions, contradictions, and abstentions for each.

**Exit:** ingesting the drift zoo is deterministic across two runs (identical KB snapshots), and every seeded scenario's expected routing outcome (supersede / contradict / corroborate / abstain) is asserted by tests.

### M1: Drift Radar *(0.1, ~8 weeks)*

- ING-1, 2, 4 to 11 (all P0 ingestion except wiki). DRF-1 to 5, 7.
- CLI: `ingest`, `drift`, `explain`, `history`, `as-of`, `blame`, `check` (exit code plus SARIF).
- Exporters: SARIF and JSON snapshot.
- Dogfood on **Ontolith's own repository**. Its SPEC's "Implementation deviations" notes are hand-labeled drift, which makes a useful real-world recall check.

**Exit:** on the drift zoo, **precision ≥ 95%, recall ≥ 90%**. On three real OSS Python repos (Ontolith plus two design partners), maintainers hand-label a 100-item sample of reported drift at **precision ≥ 90%**. Live-ingest and explain budgets are met on the reference repo.

### M2: Reconcile *(0.2, ~10 weeks)*

- REC-1 to 7: dispositions, suggested winners, baseline triage, waivers, suppression, re-affirm pass, introduced-drift CI gate.
- GitHub App in `plumb serve`: check runs, inline annotations, PR comment commands, identity mapping, shadow KBs, doc-fix proposal ↔ PR lifecycle.
- MCP façade AGT-1 to 4 with the closed-set test. First-party agent recipe for "fix the docs your change broke."
- Backfill with the replay clock (ING-8), and releases (ING-9).

**Exit:** the full loop (J2 → J3 → merge → corroboration) is demonstrated on a real repository with a real agent. Zero direct-write paths from any AI principal, proven by the closed-set test plus a policy conformance test ("AI proposal never auto-accepts under any configured policy"). Two design-partner teams run Plumbline in CI for four consecutive weeks, and the introduced-drift gate is not disabled by either.

### M3: Publish and Harden *(1.0, ~8 weeks)*

- OUT-1, 2 (reconciled reference site with trust badges, verified agent context). ING-3 (GitHub wiki). QRY-6 (semantic search). OUT-4 if on schedule.
- Performance budgets enforced in CI benchmarks. Hostile-input fuzzing of every parser inside the sandbox. External security review (sandbox configuration, identity mapping, MCP surface).
- Beta: AGT-6 LLM prose-claim extractor, off by default.
- Docs site, quickstart (< 15 min to first drift report), upgrade path.

**Exit:** all P0 requirements met. Budgets green. Security review has no open high-severity findings. Five production design partners. Drift-report precision ≥ 90% sustained over four weeks of partner data.

### vNext (post-1.0, ordered by expected value)

1. **TypeScript** code facts (then Go).
2. **Behavioral claims.** The beta extractor graduates, plus an LLM "auditor" `ai` principal that proposes a *code-side* canonical claim for a behavioral aspect. Both sides are then canonical and reviewed, so static routing works unchanged.
3. **Confluence/Notion** via the Connector protocol (pure data sync, sandboxed, network-scoped).
4. **Release lines / maintenance branches.** Needs a subject-scoping design (a Fact per line).
5. **Hosted offering and multi-repo dashboards.** Cross-repo queries depend on Ontolith multi-namespace support.
6. A review web UI, if GitHub proves insufficient for non-engineering doc owners.
7. Sandboxed doctest execution, as its own security-reviewed feature.

---

## 11. Success metrics

**North star: Drift half-life.** The median time from a contradiction's introducing commit to its resolution, across all repositories. It captures detection *and* follow-through. Target: under 3 business days at 1.0 for design partners, down from "unknown / months" at baseline.

| Area | Metric | 1.0 target |
|---|---|---|
| **Trust in the signal** | Drift precision = 1 − (contradictions dispositioned `extraction_error`) / (all resolved) | ≥ 90% (deterministic extractors); tracked separately for beta AI extraction |
| | Gate retention: % of repositories with the CI gate still enabled 30 days after onboarding | ≥ 80% |
| **Reconciliation** | Drift half-life (above) | < 3 business days |
| | Introduced-drift escape rate: introduced contradictions that reach the tracked branch unresolved / all introduced | < 20% |
| | Open-drift trend per repository after baseline triage | Monotonically non-increasing over 8 weeks |
| **Coverage** | Verified-fact ratio: documented facts with ≥ 1 code-corroborated claim / all documented checkable facts | Reported, no target in 1.0 (baseline first) |
| | Abstention rate: projector abstentions / projection attempts | Reported. A sudden rise is an alert (analysis regression). |
| **AI participation** | AI doc-fix acceptance rate | Reported; > 60% is healthy |
| | AI doc-fix reversal rate: accepted AI fixes whose claims are contradicted again within 30 days *without* an intervening code change | < 5% |
| | AI-authored assertions landed without review | **0, as an invariant.** Any non-zero value is a P0 bug. |
| **Adoption** | Time to first drift report from install | < 15 min |
| | Weekly active reviewers (distinct humans resolving or approving) per repository | ≥ 2 on team repos |

---

## 12. Risks

| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| R1 | **False positives kill adoption.** Exact-equality routing means any canonicalization gap becomes a bogus contradiction. | High / Critical | Atomic aspects, abstention-first projector, the canonical-value Validator at every commit point, precision gates at every milestone exit, `extraction_error` disposition feeding metrics and suppression |
| R2 | **Onboarding flood.** Backfill of a large repository produces hundreds of historical contradictions and the team gives up. | High / High | Baseline triage with suggested winners, a CI gate on *introduced* drift only, backlog shown as a trend rather than a wall |
| R3 | **Some aspects can never prove absence** (`raises`, `exists` in dynamic code), so drift there is invisible. | Certain / Medium | Honest labeling: corroboration-only aspects are marked "verified-or-unverified," never "no drift." The coverage report makes the blind spots explicit. |
| R4 | **Resolution retracts agreeing members.** Ontolith's `resolve_contradiction` keeps one winner and retracts the rest, including members whose value equals the winner's. | Certain / Low | Re-affirm pass (REC-5) re-asserts current matching claims as corroboration, with a clear provenance trail. Upstream ask U1: an option to keep same-value members active on resolution. |
| R5 | **Retracting projections muddies semantics.** "Retracted" normally means "was wrong"; for a projection it means "no longer current." | Certain / Low | L1 holds the correct history. Projection retractions carry a structured rationale (`"code changed at <sha>; see L1 <assertion>"`). Upstream ask U3: static-predicate window closure for derived-mirror predicates. |
| R6 | **KB loss = loss of human decisions** that can't be rebuilt from Git | Medium / High | Documented backup, `plumb backup`, and a decisions export (resolutions and waivers as JSON) that can be replayed into a rebuilt KB |
| R7 | **Replay-clock backfill is debatable bitemporal practice** | Medium / Medium | Explicit ADR, always-real `metadata.ingested_at`, and the substitution restricted to Git-sourced history at onboarding |
| R8 | **Sandbox residual gaps** (Ontolith KI-110/111), and no enforcement on macOS/Windows | Medium / High (hostile repos) | Linux-only production support, `require_enforcement=True`, parser fuzzing, a bytes-only plugin interface, a watchdog timeout |
| R9 | **Plumbline ends up as "yet another docs bot"** that devs mute | Medium / High | Review lives in GitHub, digests instead of pings, a precision bar before any GitHub App GA, nothing auto-resolved and nothing auto-committed |
| R10 | **Scope pull toward behavioral/prose verification** before the structural core is trusted | High / Medium | Hard non-goal for 1.0 (§4.2). The beta extractor ships only behind a flag and is measured separately. |
| R11 | **Substrate coupling:** an Ontolith 2.0 break or a missing capability blocks us | Low / Medium | Pin `<2.0`. Ontolith's SemVer and format-version freeze apply. Upstream asks U1 to U3 are workarounds, not blockers. |
| R12 | **Identity mapping errors** attribute a review act to the wrong human | Low / High | Verified-email-only mapping, unattributable approvals don't count, admin-auditable mapping table recorded as admin events |

---

## 13. Open questions

These are real forks I haven't closed. Each has an owner, a deadline, and my current leaning.

1. **Should the tracked-branch projection be the *only* code truth, or should the latest release also be a truth source?** Docs often describe the released version, not `main`. Leaning: v1 compares against `main` (drift is caught earliest), and reports mark "fact differs from latest release" as context. *Decide in M1 with design partners.*
2. **Where exactly should the CI gate's severity threshold sit by default?** Leaning: fail on introduced `exists`, `param.*.exists`, and `removed_in` drift (things that break copy-paste). Warn on defaults, types, and deprecation. *Decide from M1 dogfood data.*
3. **Doc-fix PR granularity:** one PR per contradiction, per page, or per originating code PR? Leaning: per originating code PR when it exists, otherwise per page. *Validate with design partners in M2.*
4. **Should unattributable GitHub approvals be allowed to *start* a resolution that a mapped human then confirms?** Leaning no (simplicity), but OSS projects with many unmapped maintainers may push back.
5. **Authority map defaults** (§7.6): are docstrings more authoritative than the README? It varies by project. Leaning: ship defaults, make them per-repository config, and revisit once upstream U2 lands.
6. **Keep L1 facts for symbols no doc mentions?** Useful for time travel ("when did this private function's signature change?") but it roughly triples KB size. Leaning: yes for public symbols (no leading underscore, or in `__all__`), no for private ones.

**Upstream asks to Ontolith** (none of them blocks 1.0):

- **U1:** optional retention of same-value members on `resolve_contradiction`.
- **U2:** `PluginRegistry.register(trust_level=…)`, so per-source authority can use native `.trust_at_least()`.
- **U3:** a sanctioned way to close a `static` assertion's validity window for derived-mirror predicates (would remove the retract-then-project pattern).
- **U4:** remote `QueryBuilder`/`AsOfView` for isolated plugins (KI-101), which would simplify the reasoners.
- **U5:** a plugin call timeout (KI-102), which would let us delete our watchdog.

---

## 14. Worked examples

These cases shaped §7. Each shows exactly which Ontolith mechanism fires.

| # | Scenario | L1 (time_varying) | L2 `Fact.value` (static) | Outcome |
|---|---|---|---|---|
| 1 | `connect(timeout=30)` → `connect(timeout=60)`; docstring updated in the **same commit** | `signature_json` **superseded** | Commit-apply: projection `30` retracted; docstring claim `30` retracted (source no longer says it); projection `60` asserted; docstring claim `60` asserted → **corroboration** | No drift, and no review needed. History is intact: `as_of(before)` shows `30` in both layers. |
| 2 | Same change; README table still says `30` | superseded | README claim `30` (active, window open) vs. new projection `60` → **contradiction** (members: README claim, projection) | Drift, introduced by that commit. Suggested disposition: `docs_stale`. |
| 3 | README says `30`, wiki says `45`, code says `30` | unchanged | Wiki claim `45` collides with the projection `30` and the README claim `30` → contradiction (3 members) | `doc_vs_doc_vs_code`. Suggested winner: the projection. The README is shown as agreeing, the wiki as stale. |
| 4 | Refactor flips `parse(strict=True)` to `False`; four doc sources say `True` | superseded | Projection `False` vs. four claims `True` → contradiction | Human decides `code_defect`: the doc claim wins, the projection is retracted, and a Waiver suppresses re-projecting `False`. When the code is reverted, the new projection `True` corroborates and the waiver expires. |
| 5 | `old_fn` renamed to `new_fn`; README still calls `old_fn()` | `Symbol(old_fn).present` superseded to `false`; `new_fn` created | Projection `old_fn#exists=false` vs. README claim `true` → contradiction | Drift, with a rename hint (DRF-6) in the suggested fix |
| 6 | Module defines `__getattr__`; README mentions `acme.plugins.fancy` | Symbol not statically resolvable | **Projector abstains**; the README claim stays unverified | No drift reported. Counted in coverage as unverified. |
| 7 | CHANGELOG says "Removed `foo` in 2.1", but history shows `foo` present at the 2.1 tag and gone at 2.2 | `present` superseded at a commit between the 2.1 and 2.2 tags | Lineage reasoner projects `foo#removed_in = "2.2"` vs. changelog claim `"2.1"` → contradiction | Drift in the changelog. This is a *historical* fact about a release, so it is `static` and correct to dispute. |
| 8 | ADR-0005 (Superseded) says "we use Postgres" | n/a | No claims extracted (ING-4) | No drift. ADRs are historical records, and extracting claims from them would manufacture disputes. |
| 9 | Agent proposes a README fix whose new text says default `90` (hallucinated) | n/a | `DocSection.text` proposal → `RequireReview`. The shadow-KB delta returned to the agent shows it would open a new contradiction. | Caught before any human is asked. If a human approves anyway, post-merge ingest opens the contradiction, attributed to the AI-authored fix. |
| 10 | Docstring says `timeout: int`; annotation is `int | None` | unchanged | `param.timeout.type`: canonical `int` vs. `int | None` → contradiction | Real drift (the docs omit `None`). If the team considers this noise, they use the `intentional_simplification` waiver per fact, or disable the `type` aspect per path in config. |
| 11 | README says "Requires Python 3.9+"; `pyproject` says `>=3.11` | `project.requires_python` superseded when bumped | Claim `>=3.9` vs. projection `>=3.11` → contradiction | Drift, surfaced the moment the bump landed |

---

## 15. Decisions recorded

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Where drift detection lives | **Ontolith static conflict routing on a per-fact slot.** No separate diff engine. | One mechanism, with governance, provenance, and time travel for free. Drift *is* "sources disagree about a static fact." |
| 2 | Temporality model | **Two layers, one rule:** code history on `time_varying`, reconciliation on `static`. Doc claims never touch `time_varying`. | A shared predicate either lets stale docs overwrite code (time_varying) or floods review with code evolution (static) |
| 3 | Unit of a claim | **Atomic aspect per `(symbol, aspect)` Fact**, canonical values | Docs state partial facts, and exact-equality routing needs matching granularity |
| 4 | Precision stance | **Deterministic extractors, abstention-first projector.** LLM extraction is beta and always reviewed. | A noisy drift tool gets muted, and trust is the product |
| 5 | Source of truth for doc text | **The repository.** The KB is the source of truth for reconciliation state. | Docs stay where developers edit them. No lock-in, no dual-write. |
| 6 | Review surface | **GitHub PRs and check runs, plus the CLI.** No review web app in 1.0. | Meet reviewers where they already approve changes |
| 7 | AI participation | **Agents are `ai` principals: propose only, always reviewed, closed-set MCP façade.** LLM components are never plugins. | Mirrors Ontolith's invariant and closes the `service`-principal side door |
| 8 | Git authors | **Recorded in metadata, not as principals** | Principals carry authentication and capability. Committers don't act in Plumbline. |
| 9 | Backfill time semantics | **Replay clock** (asserted_at = commit time), with real ingest time in metadata | Makes `as_of(release)` work on onboarded history and makes `blame` mean "when introduced" |
| 10 | Scope | **Python + Git-hosted docs, one branch, one KB per repository, self-hosted** | A narrow, deep 1.0 that can hit a 90% precision bar |
| 11 | Resolution | **Always a human, one attributed resolution per contradiction.** A merge of a Plumbline-linked fix PR counts as that human's act. | Accountability can't be delegated to a service principal |

---

## Appendix A: Naming

**Plumbline** was chosen for clarity (checking that something is true against a reference that doesn't lie), a short CLI verb (`plumb check`, `plumb blame`), and a metaphor that matches the product: gravity is the code, and the plumb line shows whether the docs hang true. Alternatives considered: **Concordance** (agreement across sources; long), **Palimpsest** (layered historical writing, a strong bitemporal metaphor, but hard to spell), **Corroborate**, **Trueline**, **Driftwatch** (too alarm-centric). Package, domain, and trademark clearance are pending.

## Appendix B: Glossary

- **Code fact (L1).** A `time_varying` assertion about a `Symbol` derived from static analysis at a commit, such as its signature, presence, or deprecation.
- **Fact (L2 slot).** An entity per `(symbol, aspect)` whose `static` `Fact.value` predicate is where all sources' claims meet.
- **Doc claim.** An assertion on `Fact.value` made by a doc importer principal, anchored to a file, line range, and commit.
- **Projection.** The drift projector's assertion on `Fact.value` stating the code's current value. Retracted when the code changes (L1 holds the history).
- **Drift.** An open Ontolith contradiction on a `Fact.value` slot.
- **Corroboration.** Multiple active assertions with the same value on one slot. Each keeps its own confidence, and nothing is combined.
- **Abstention.** The projector declining to assert a value it can't determine. The result is "unverified," never drift.
- **Disposition.** Plumbline's classification of a resolution: `docs_stale`, `code_defect`, `doc_vs_doc`, `extraction_error`, or `intentional_simplification`.
- **Waiver.** A reviewed, static record suppressing re-projection of a specific code value for a fact.
- **Shadow KB.** A throwaway copy of the main KB used to compute a PR's introduced drift.
- **Anchor URI.** An immutable, SHA-pinned pointer to the exact text or code that produced an assertion.
- **Introduced drift.** Contradictions opened by a specific commit or PR, as opposed to backlog.

## Appendix C: Ontolith capabilities relied on (for dependency review)

Append-only assertions with `status`/`valid_to`/`supersedes` as the only mutable fields. Temporality × cardinality conflict routing (`static`/`single` → contradiction; `static`/`many` → coexist; `time_varying` → supersede). `as_of` with retraction- and flag-aware point-in-time semantics. `include_flagged`/`include_history` opt-ins. One-call `provenance()`. Proposal state machine (`propose`, `accept_proposal`, `reject_proposal`, `request_changes`, `resubmit`, `assign_reviewers`). `resolve_contradiction` (non-AI, review-capable, non-party resolver) and `flag_contradiction` (same subject and predicate). Policy strategies (`ThresholdPolicy`, `RequireReviewForAI`, `RequireReviewByRole`, `SourceRequired`, `SourceQuorum`, `ConfidenceThreshold`, `Composite`) as pure functions. `ai` principals with a required owner and per-assertion `model`. Delegation via `acting_as` with min-capability attenuation. `PluginRegistry` with capability ceilings and per-call process isolation (seccomp on Linux). Per-assertion `validators` at every commit point. Injected `Clock`/`IdProvider` (`Ontology.connect(clock=, id_provider=)`; the replay clock and a deterministic `SequentialIdProvider` make a backfill reproducible). `ThresholdPolicy` auto-accepting `propose()` from a `service` principal with `write`. Automatic `time_varying` supersession on `propose(valid_from=…)`. `propose_ref` and `create_entity` for `Fact` creation. `retract` refusing a *party* to an open contradiction with `CapabilityError` (a non-party's is routed to review), which the claim protocol's deferral relies on. A full `assertions(predicate=…, status=None)` scan, since assertions cannot be filtered by author or source. Lookup of an entity by natural key through the storage backend (`Ontology.backend.get_entity_by_natural_key`; there is no public `Ontology` method for it). SQLite default backend with WAL. Hybrid query (`.where`, `.semantic`, `.min_confidence`, `.trust_at_least`). MCP server with no direct-write tool and token auth. Storage format migrations. SemVer 1.0 API freeze.
