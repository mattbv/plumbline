"""The ingestion use case: the commit-apply protocol (PRD §7.7).

Each commit is applied in a fixed order so transient intermediate states
never create false contradictions: L1 code facts first, then retract
stale L2 projections and claims, then assert the new ones. See ADR-0001
for why L1 and L2 need this ordering at all.

M0 scaffold note: this class defines the real orchestration shape and is
exercised by `tests/unit/application/test_ingest.py` against fake ports --
the actual `CodeImporter`/`DocImporter` implementations (M1, PRD ING-1/2)
are what turn this from a structurally-correct no-op into real ingestion.
"""

from __future__ import annotations

from dataclasses import dataclass

from plumbline.application.ports import (
    CodeImporter,
    CommitRef,
    DocImporter,
    KnowledgeBase,
    RepoReader,
)


@dataclass(slots=True)
class IngestOneCommit:
    """Applies one commit through the fixed six-step commit-apply protocol."""

    repo: RepoReader
    code_importer: CodeImporter
    doc_importers: tuple[DocImporter, ...]
    kb: KnowledgeBase

    def run(self, commit: CommitRef) -> None:
        """Apply `commit` to the KB (PRD §7.7, steps 1-5; step 6 is `ReconcileDrift`)."""
        files = {path: self.repo.read_file_at(path, commit.sha) for path in commit.changed_paths}

        # 1. L1: code facts (supersession).
        for claim in self.code_importer.extract(files, commit):
            self.kb.record_code_fact(
                claim.symbol_key, claim.aspect, claim.raw_value, as_of=commit.committed_at
            )

        # 2-5. Projection/claim retract+assert is the drift projector's job
        # (a Reasoner, PRD §7.8) -- not this use case's. IngestOneCommit's
        # own responsibility ends at getting L1 and raw doc claims into the
        # KB; ReconcileDrift (M1) runs the projector and claim bookkeeping
        # this docstring's steps 2-5 describe.
        for importer in self.doc_importers:
            for claim in importer.extract(files, commit):
                self.kb.record_claim(
                    claim, author_principal="plumb-doc-importer", as_of=commit.committed_at
                )
