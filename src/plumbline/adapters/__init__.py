"""Adapters: concrete implementations of `plumbline.application.ports`.

Everything that actually touches Ontolith, Git, the filesystem, a network
call, or GitHub's API lives here -- never in `domain` or `application`
(enforced by the `import-linter` contract in pyproject.toml).
"""
