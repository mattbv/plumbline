"""Pure domain logic: the aspect catalog, canonicalization, anchors, dispositions.

Nothing in this package touches Ontolith, Git, the filesystem, or a network —
enforced by the `import-linter` contract in pyproject.toml. This is what
`plumbline.application`'s use cases orchestrate and what `plumbline.adapters`
translates real-world input into.
"""
