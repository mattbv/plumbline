"""Ingesting a real Git repository must equal ingesting the same history synthetically.

The drift zoo exists twice: as in-memory scenarios (`ZooHistory`, with made-up SHAs) and as
a genuine Git repository built from them (`builder.build`). The same pipeline, run over
each, must leave the knowledge base in the same state. That ties the Git reader, with its
rename-free diffs, path filters and clamped times, to everything verified so far.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ontolith.core.ids import SequentialIdProvider

from plumbline.adapters.docstring_claim_importer import DocstringClaimImporter
from plumbline.adapters.git_reader import GitRepoReader
from plumbline.adapters.ontolith_kb import OntolithKnowledgeBase
from plumbline.adapters.python_code_importer import PythonCodeImporter
from plumbline.application.ports import RepoReader
from plumbline.application.use_cases.backfill import BackfillHistory, IngestTotals
from plumbline.application.use_cases.ingest import IngestOneCommit
from tests.zoo import builder
from tests.zoo.importing import ZooHistory
from tests.zoo.scenarios import ALL

pytestmark = pytest.mark.integration


def _ingest(reader: RepoReader, db: Path) -> tuple[OntolithKnowledgeBase, IngestTotals]:
    kb = OntolithKnowledgeBase.initialize(
        db,
        admin_principal_id="admin@zoo.invalid",
        replay=True,
        id_provider=SequentialIdProvider(prefix="id"),
    )
    use_case = IngestOneCommit(
        repo=reader,
        code_importer=PythonCodeImporter("zoo", "zoo"),
        doc_importers=(DocstringClaimImporter("zoo", "zoo"),),
        kb=kb,
        repo_slug="zoo/zoo",
    )
    return kb, BackfillHistory(reader, use_case).run()


def _state(kb: OntolithKnowledgeBase) -> dict[str, object]:
    """Everything the KB believes, minus the SHA-bearing provenance."""
    o = kb._kb
    symbols = {e.natural_key: kb.symbol_fields(e.natural_key) for e in o.query("Symbol").all()}
    claims = {
        f.natural_key: sorted((c.author, c.value) for c in kb.claims_on(f.natural_key))
        for f in o.query("Fact").all()
    }
    disputes = sorted(i.fact_key for i in kb.open_drift())
    return {"symbols": symbols, "claims": claims, "disputes": disputes}


@pytest.fixture(scope="module")
def both(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[tuple[OntolithKnowledgeBase, IngestTotals], tuple[OntolithKnowledgeBase, IngestTotals]]:
    root = tmp_path_factory.mktemp("equiv")
    built = builder.build(ALL, root / "repo")
    via_git = _ingest(GitRepoReader(built.root), root / "git.db")
    via_memory = _ingest(ZooHistory(ALL), root / "memory.db")
    return via_git, via_memory


def test_the_same_history_gives_the_same_symbols_claims_and_disputes(both) -> None:  # type: ignore[no-untyped-def]
    (git_kb, _), (memory_kb, _) = both
    git_state, memory_state = _state(git_kb), _state(memory_kb)
    assert len(memory_state["symbols"]) > 150  # type: ignore[arg-type]
    assert git_state["symbols"] == memory_state["symbols"]
    assert git_state["claims"] == memory_state["claims"]
    assert git_state["disputes"] == memory_state["disputes"]


def test_and_does_the_same_work_to_get_there(both) -> None:  # type: ignore[no-untyped-def]
    (_, git_totals), (_, memory_totals) = both
    assert git_totals == memory_totals
    assert git_totals.commits == sum(len(s.commits) for s in ALL)
