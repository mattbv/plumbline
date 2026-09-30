"""User-facing entrypoints (CLI today; a GitHub App server is M2, PRD §7.8).

Wires concrete adapters to use cases and nothing else -- no business logic
lives here (enforced by keeping this the outermost layer in the
`import-linter` "layers" contract).
"""
