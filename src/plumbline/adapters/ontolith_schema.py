"""The Ontolith class-DSL schema Plumbline applies to its knowledge base (PRD §7.5).

Two layers, one rule (ADR-0001): code history lives on `time_varying`
properties (`Symbol.*`); reconciliation lives on one `static`,
single-valued slot per checkable fact (`Fact.value`). Doc claims never
touch a `time_varying` predicate -- see ADR-0001 for why collapsing the two
layers breaks either way.

Every `Ref["ConceptName"]` below carries a `# type: ignore[type-arg]`:
Ontolith's `Ref.__class_getitem__` is dynamic (it returns
`Annotated[str, _RefMarker(...)]` at class-body-execution time, and
genuinely requires the string form -- ruff's UP037 would otherwise strip
the "unnecessary" quotes and break schema compilation at import time, which
is why UP037 is disabled project-wide in pyproject.toml), and mypy's static
view of the stub can't see through that, always reporting "expects no type
arguments". Verified directly that the runtime relation still resolves its
target concept correctly with the ignore in place.
"""

from __future__ import annotations

from ontolith import Boolean, Concept, DateTime, Property, Ref, Relation, Text
from ontolith.schema import SchemaIR, compile_schema

SCHEMA_NAMESPACE = "default"
SCHEMA_VERSION = 1


class Release(Concept):
    """A tagged release on the tracked branch. natural_key: the version string, e.g. "2.3.0"."""

    tag: Text
    commit_sha: Text
    released_at: DateTime


class Symbol(Concept):
    """A Python symbol (function, method, class, module, ...).

    natural_key: the qualified symbol key, e.g. "py:acme.client.Client.connect".

    Everything below is `time_varying`: code changing over time is expected,
    and Ontolith's supersession -- not contradiction -- is the correct
    routing for it (ADR-0001). This is L1 in the PRD's two-layer model: the
    faithful history of what the code *was* at every commit.
    """

    kind: Text
    """function | method | class | module | cli_command | env_var | project"""

    defined_at: Text = Property(temporality="time_varying")
    """Anchor URI of the current definition; moves on refactor."""

    signature_json: Text = Property(temporality="time_varying")
    """Full canonical signature, kept for history/as_of even though drift
    detection itself works off the atomic `Fact` aspects, not this blob."""

    is_deprecated: Boolean = Property(temporality="time_varying")

    present: Boolean = Property(temporality="time_varying")
    """False after deletion. The window closes; history is kept, never deleted."""


class Fact(Concept):
    """The reconciliation slot for one `(symbol, aspect)` pair (PRD §7.2/§7.4).

    natural_key: "<symbol_key>#<aspect>", e.g.
    "py:acme.client.Client.connect#param.timeout.default".

    This is L2 in the two-layer model. `value` is `static` and single-valued
    (the class DSL's own default) -- deliberately: at any instant a checkable
    fact has one true value, and two sources stating different values *is*
    a disagreement, which is the entire drift-detection mechanism (ADR-0001).
    Every doc-claim importer and the drift projector write to this one
    predicate; nothing here is `time_varying`.
    """

    about: Ref["Symbol"] = Relation()  # type: ignore[type-arg]  # see module docstring's mypy note
    aspect: Text
    value: Text
    """THE drift detector. Do not add a `temporality="time_varying"` override
    here -- see ADR-0001 for exactly why that breaks the whole model."""


class DocSource(Concept):
    """One documentation source: a README, a wiki, a docstring set, a changelog.

    natural_key: "readme:README.md", "wiki:Tuning", "docstring:<module>", etc.
    """

    kind: Text
    """readme | docs | docstring | changelog | wiki | adr"""

    path: Text = Property(temporality="time_varying")
    """Files get renamed; this tracks the current path."""


class DocSection(Concept):
    """A stable, addressable unit of authored prose within a `DocSource`.

    natural_key: "<doc_source_key>::<stable heading path or symbol>".
    """

    in_source: Ref["DocSource"] = Relation()  # type: ignore[type-arg]

    text: Text = Property(temporality="time_varying")
    """Doc edits supersede -- editing prose is expected change, and this
    enables `as_of` rendering of historical docs. Doc *text* never
    participates in drift directly; only the claims extracted from it do."""

    mentions: Ref["Fact"] = Relation(cardinality="many")  # type: ignore[type-arg]
    """A section legitimately mentions many facts at once -- static+many
    coexist rather than dispute (ADR-0017 in Ontolith's own SPEC)."""


class Waiver(Concept):
    """A human-reviewed record suppressing re-raising of one specific drift case.

    Always created via a reviewed proposal, never directly -- a waiver is a
    decision, and changing it means a new waiver, not an edit (append-only,
    same as everything else Plumbline writes).
    """

    fact: Ref["Fact"] = Relation()  # type: ignore[type-arg]
    disposition: Text
    """One of `plumbline.domain.dispositions.Disposition`'s values."""
    suppressed_value: Text
    """The exact canonical value not to re-raise."""
    issue_url: Text | None = None


def build_schema() -> SchemaIR:
    """Compile the Plumbline schema for `Ontology.apply_schema()`.

    Returns:
        A compiled `SchemaIR`, versioned as `SCHEMA_VERSION` in
        `SCHEMA_NAMESPACE` -- pass straight to `kb.apply_schema(schema,
        author=...)` during `plumb init`.
    """
    return compile_schema(
        SCHEMA_NAMESPACE,
        SCHEMA_VERSION,
        Release,
        Symbol,
        Fact,
        DocSource,
        DocSection,
        Waiver,
    )
