"""The ingestion pipeline, wired once.

`plumb ingest` and the seeded-drift measurement must run *exactly* the same pipeline, or the
measurement would say nothing about the tool. This is the single place where the importers,
the reader and the knowledge base are put together.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from plumbline.adapters.docstring_claim_importer import DocstringClaimImporter
from plumbline.adapters.git_reader import DEFAULT_EXCLUDE, GitRepoReader, repo_slug
from plumbline.adapters.ontolith_kb import OntolithKnowledgeBase
from plumbline.adapters.python_code_importer import PythonCodeImporter
from plumbline.application.use_cases.backfill import BackfillHistory
from plumbline.application.use_cases.ingest import IngestOneCommit


@dataclass(slots=True)
class Pipeline:
    """A knowledge base together with everything that fills it from one repository."""

    kb: OntolithKnowledgeBase
    reader: GitRepoReader
    backfill: BackfillHistory
    slug: str


def open_pipeline(
    repo_root: Path,
    kb_path: Path,
    *,
    admin: str = "plumbline@localhost",
    branch: str | None = None,
    exclude: Sequence[str] = (),
) -> Pipeline:
    """Open (creating if absent) the KB at ``kb_path`` and wire it to read ``repo_root``.

    Backfill mode: each write is pinned to its commit's time (PRD §7.7).
    """
    if kb_path.exists():
        kb = OntolithKnowledgeBase.open(kb_path, replay=True)
    else:
        kb_path.parent.mkdir(parents=True, exist_ok=True)
        kb = OntolithKnowledgeBase.initialize(kb_path, admin_principal_id=admin, replay=True)
    slug = repo_slug(repo_root)
    owner, _, name = slug.partition("/")
    reader = GitRepoReader(repo_root, branch=branch, exclude=(*DEFAULT_EXCLUDE, *exclude))
    ingest = IngestOneCommit(
        repo=reader,
        code_importer=PythonCodeImporter(owner, name),
        doc_importers=(DocstringClaimImporter(owner, name),),
        kb=kb,
        repo_slug=slug,
    )
    return Pipeline(kb, reader, BackfillHistory(reader, ingest), slug)
