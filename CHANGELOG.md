# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Type comparison no longer reports differences in spelling (quotes, `List` against `list`,
  `Optional` against `| None`), reads a documented `optional` as allowing `None`, and stays
  silent where it cannot prove a difference (an unresolved name that may be an alias, or a
  bare generic against its parameterization, or `Literal` values documented as their type).
  Docs that omit `None` where the code allows it are still reported. See ADR-0007 Amendments 3 and 4.
- `100` and `100.0` are the same default, and a quoted word *default* in a sentence is no
  longer read as the keyword.

- A property no longer has a signature stated for it (its docstring describes the object it
  returns); deprecation is stated `true` when a leading warning says so and `false` only when
  nothing could be hiding a marker; a `.. deprecated::` nested in a parameter no longer
  deprecates the function; a documented `default None` allows `None`; docs naming a supertype
  of the annotation do not differ provably; and a code default of `None` against a documented
  concrete default is no longer reported. See ADR-0004 Amendment 3 and ADR-0007 Amendment 5.

### Added

- M0 foundations scaffold: clean-architecture package layout
  (`domain`/`application`/`adapters`/`interfaces`), enforced by an
  `import-linter` dependency-rule contract.
- The Ontolith class-DSL schema (`Release`, `Symbol`, `Fact`, `DocSource`,
  `DocSection`, `Waiver`) implementing the two-layer reconciliation model —
  see ADR-0001.
- `plumb init` — creates `plumbline.toml` and a real Ontolith-backed
  knowledge base with the schema applied and an admin principal registered.
- `plumb --version`, and stubbed `ingest`/`drift`/`explain`/`as-of`/
  `blame`/`check` subcommands with settled argument shapes (real
  implementation is M1).
- Pure domain logic: the aspect catalog, value canonicalization, anchor
  URI parsing, and resolution dispositions (PRD §7.4/§7.3/§7.6) — fully
  tested, no external dependencies.
- ADR-0001 (two-layer reconciliation model) and ADR-0002 (ports as
  `Protocol`s).
- CI: format/lint/type/import-linter/test/security gates.

<!-- No tags exist yet -- add a compare link here once the first one does. -->
