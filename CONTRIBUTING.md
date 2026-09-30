# Contributing to Plumbline

Thank you for your interest in contributing! This document covers the
project's development workflow and quality gates.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Architecture](#architecture)
- [Development Workflow](#development-workflow)
- [Testing Requirements](#testing-requirements)
- [Code Quality Standards](#code-quality-standards)
- [Commit Message Guidelines](#commit-message-guidelines)

## Code of Conduct

This project adheres to a Code of Conduct that all contributors are
expected to follow. Please read [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
before contributing.

## Getting Started

### Prerequisites

- Python ≥ 3.11
- [uv](https://github.com/astral-sh/uv) for dependency management
- Ontolith isn't on PyPI yet — `pyproject.toml` pins it via a direct git
  reference to a tagged release, so `uv sync` needs network access to
  `github.com` on first install.

### Initial Setup

```bash
git clone https://github.com/mattbv/plumbline.git
cd plumbline

# Install dependencies (including dev tools)
uv sync --all-extras

# Install pre-commit hooks
uv run pre-commit install

# Run the test suite to verify setup
uv run pytest
```

### Running Quality Gates

```bash
uv run ruff format          # Format code
uv run ruff check           # Lint
uv run mypy --strict src    # Type check
uv run lint-imports         # Dependency-rule contract (see Architecture below)
uv run pytest               # All tests (unit + integration, coverage ≥85%)
uv run bandit -r src/plumbline -c pyproject.toml   # Static security scan
uv run interrogate -c pyproject.toml src/plumbline  # Docstring coverage (≥90%)

# Full gate, run before pushing
uv run ruff format --check && uv run ruff check && uv run mypy --strict src \
  && uv run lint-imports && uv run pytest
```

## Architecture

Plumbline follows the same ports-and-adapters (hexagonal) architecture
Ontolith itself uses.

### Dependency Rule (CI-enforced via `import-linter`)

- `plumbline.domain` must not import `plumbline.application`,
  `plumbline.adapters`, or `plumbline.interfaces`. It's pure logic — no
  I/O, no Ontolith import, nothing that can't run in an empty sandbox.
- `plumbline.application` must not import `plumbline.adapters` or
  `plumbline.interfaces`. Use cases depend only on the abstract
  `Protocol`s in `plumbline.application.ports` (ADR-0002).
- Layer order is `interfaces → adapters → application → domain`. A
  contract violation is a CI failure, not a lint warning.

See [ADR-0001](docs/adr/ADR-0001-two-layer-reconciliation-model.md) before
touching the schema or anything that writes to the knowledge base — it's
the core modeling decision the whole architecture follows from.

### A note on the Ontolith schema (`plumbline.adapters.ontolith_schema`)

Every `Ref["ConceptName"]` relation needs the literal string quotes —
Ontolith's `Ref.__class_getitem__` requires them at runtime, and `ruff`'s
`UP037` rule (which strips "unnecessary" forward-reference quotes) is
disabled project-wide specifically because it silently broke this once.
Don't re-enable it without reading that module's own docstring.

## Development Workflow

### 1. Create a Branch

Never commit directly to `main`.

```bash
git checkout -b <type>/<short-description>
```

Branch naming: `feat/<description>`, `fix/<description>`,
`docs/<description>`, `test/<description>`, `refactor/<description>`,
`m<N>/<description>` for work scoped to a specific milestone (see
[Implementation Plan](docs/Implementation_Plan.md)), e.g. `m1/code-importer`.

### 2. Make Your Changes

- Write tests first for new functionality where practical, especially for
  anything in `plumbline.domain` (pure logic is the cheapest thing in this
  codebase to property-test).
- Keep commits atomic and focused.
- Run quality gates frequently during development.

### 3. Commit

We use [Conventional Commits](https://www.conventionalcommits.org/):

```bash
git commit -m "type(scope): description"
```

See [Commit Message Guidelines](#commit-message-guidelines) below.

### 4. Push and Open a Pull Request

```bash
git push -u origin your-branch
gh pr create
```

### Review Process

1. CI must pass (all quality gates green).
2. At least one maintainer approval required.
3. All review comments resolved.

## Testing Requirements

- **Unit tests** (`tests/unit/`) — pure functions and use cases against
  fakes. No real Ontolith connection, no real Git repository, no network.
- **Integration tests** (`tests/integration/`), marked
  `@pytest.mark.integration` — exercise a real Ontolith-backed knowledge
  base (a real SQLite file in a temp directory). Still no network.
- **Coverage**: ≥85% package-wide, CI-enforced (`--cov-fail-under=85` in
  `pyproject.toml`). `plumbline.domain` is the highest-value place to push
  this higher, since it's pure and cheap to test exhaustively.

## Code Quality Standards

| Check | Tool | Requirement |
|---|---|---|
| Format | `ruff format --check` | Clean |
| Lint | `ruff check` | Zero errors |
| Types | `mypy --strict` | Zero errors on `src/` |
| Tests | `pytest` | All pass, ≥85% coverage |
| Dependency rule | `import-linter` | Contract holds |
| Static security | `bandit` | No unsuppressed mediums+ |
| Docstrings | `interrogate` | ≥90% on public API |
| Commit messages | Conventional Commits | Conformant |

## Commit Message Guidelines

Format: `<type>(<scope>): <description>`

**Types:** `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`, `ci`

**Scopes:** the layer or module touched — `domain`, `application`,
`adapters`, `interfaces`, `cli`, `schema`, `ci`, `adr`

**Examples:**

```bash
feat(domain): add canonicalization for env-var aspects
fix(adapters): handle a DuckDB-shaped natural key collision
docs(adr): record ADR-0003 on the drift projector's abstention policy
test(application): cover IngestOneCommit's retract ordering
```

## License

By contributing to Plumbline, you agree that your contributions will be
licensed under the Apache-2.0 License.

Thank you for contributing!
