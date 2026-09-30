"""Use cases and ports. Depends on `plumbline.domain` and on its own abstract
`ports` only -- never on a concrete adapter (enforced by the `import-linter`
contract in pyproject.toml). This is the layer that would stay unchanged if
Ontolith were swapped for another substrate, or Git for another VCS.
"""
