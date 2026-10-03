"""The four-pass commit apply with the projector in it (ADR-0007), against fakes.

The order is the contract: retract projections, retract doc claims, assert projections,
assert doc claims. Applied in any other order a commit that fixes the code and the docs
together opens a false contradiction that the importers are then forbidden to clear.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from plumbline.adapters.python_code_importer import PythonCodeImporter
from plumbline.application.ports import CommitRef, RawClaim
from plumbline.application.use_cases.ingest import DeferredClaim, IngestOneCommit, IngestReport
from tests.unit.application.test_ingest import FakeDocImporter, FakeKnowledgeBase

SHA = "abcdef0123456789abcdef0123456789abcdef01"
T0 = datetime(2026, 1, 1, tzinfo=UTC)
F = "py:pkg.m.f"
FACT = f"{F}#param.timeout.default"


def source(default: int, *, dynamic: bool = False) -> bytes:
    extra = "\n\ndef __getattr__(name):\n    raise AttributeError(name)\n" if dynamic else ""
    return f"def f(host, timeout={default}):\n    return host\n{extra}".encode()


class Repo:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def first_parent_history(self, *, since: datetime | None = None) -> list[CommitRef]:
        return []

    def read_file_at(self, path: str, commit_sha: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]


def readme_claim(aspect: str, value: str, symbol: str = F) -> RawClaim:
    return RawClaim(symbol, aspect, value, f"repo://o/r@{SHA}/README.md#L1-L1", 0.9, "md.table")


class Harness:
    def __init__(self) -> None:
        self.kb = FakeKnowledgeBase()
        self.repo = Repo()
        self.readme = FakeDocImporter([], principal="plumb-readme")
        self.clock = T0
        self.use_case = IngestOneCommit(
            repo=self.repo,
            code_importer=PythonCodeImporter("o", "r"),
            doc_importers=(self.readme,),
            kb=self.kb,
            repo_slug="o/r",
        )

    def commit(
        self, *, code: bytes | None = None, claims: list[RawClaim] | None = None
    ) -> IngestReport:
        changed = []
        if code is not None:
            self.repo.files["pkg/m.py"] = code
            changed.append("pkg/m.py")
        if claims is not None:
            self.readme.claims = claims
            self.repo.files["README.md"] = b"x"
            changed.append("README.md")
        self.kb.authored.clear()
        self.clock += timedelta(hours=1)
        return self.use_case.run(CommitRef(SHA, self.clock, tuple(changed)))

    def present(self, author: str) -> set[str]:
        return {v for a, _, v, _ in self.kb.stored.values() if a == author}


def started() -> Harness:
    h = Harness()
    h.commit(code=source(30), claims=[readme_claim("param.timeout.default", "30")])
    return h


class TestOrder:
    def test_fixing_the_code_and_the_docs_together_runs_the_four_passes_in_order(self) -> None:
        h = started()
        h.commit(code=source(60), claims=[readme_claim("param.timeout.default", "60")])
        assert h.kb.authored == [
            ("retract", "plumb-projector"),
            ("retract", "plumb-readme"),
            ("assert", "plumb-projector"),
            ("assert", "plumb-readme"),
        ]

    def test_it_ends_with_both_authors_agreeing(self) -> None:
        h = started()
        h.commit(code=source(60), claims=[readme_claim("param.timeout.default", "60")])
        assert h.present("plumb-projector") == h.present("plumb-readme") == {"60"}

    def test_a_first_claim_is_projected_in_the_same_commit(self) -> None:
        h = Harness()
        report = h.commit(code=source(30), claims=[readme_claim("param.timeout.default", "30")])
        assert h.present("plumb-projector") == {"30"} == h.present("plumb-readme")
        assert (report.projected, report.claims_asserted) == (1, 1)
        assert [a for k, a in h.kb.authored if k == "assert"] == ["plumb-projector", "plumb-readme"]

    def test_code_changing_alone_restates_the_projection(self) -> None:
        h = started()
        report = h.commit(code=source(60))
        assert h.present("plumb-projector") == {"60"} and h.present("plumb-readme") == {"30"}
        assert (report.projections_withdrawn, report.projected) == (1, 1)
        assert h.kb.authored == [("retract", "plumb-projector"), ("assert", "plumb-projector")]

    def test_docs_changing_alone_leaves_the_projection_untouched(self) -> None:
        h = started()
        h.commit(claims=[readme_claim("param.timeout.default", "60")])
        assert h.kb.authored == [("retract", "plumb-readme"), ("assert", "plumb-readme")]

    def test_removing_the_last_claim_withdraws_the_projection_with_it(self) -> None:
        h = started()
        report = h.commit(claims=[])
        assert h.present("plumb-projector") == set() == h.present("plumb-readme")
        assert (report.projections_withdrawn, report.claims_retracted) == (1, 1)

    def test_an_unchanged_commit_does_nothing(self) -> None:
        h = started()
        report = h.commit(code=source(30), claims=[readme_claim("param.timeout.default", "30")])
        assert h.kb.authored == []
        assert (report.projected, report.projections_withdrawn, report.deferred) == (0, 0, ())


class TestDisputes:
    def test_a_stuck_projection_is_deferred_and_no_replacement_is_piled_on(self) -> None:
        h = started()
        h.kb.disputed_facts.add(FACT)

        report = h.commit(code=source(60))

        assert report.deferred == (DeferredClaim("plumb-projector", "pkg/m.py", FACT),)
        assert (report.projections_withdrawn, report.projected) == (0, 0)
        assert h.present("plumb-projector") == {"30"}  # still the value the dispute is about

    def test_docs_in_the_same_commit_still_apply_when_only_the_projection_is_stuck(self) -> None:
        h = started()
        h.kb.disputed_facts.add(FACT)
        report = h.commit(
            code=source(60),
            claims=[
                readme_claim("param.timeout.default", "30"),  # unchanged, in the disputed fact
                readme_claim("param.timeout.exists", "true"),  # new, on a different fact
            ],
        )
        assert report.claims_asserted == 1
        assert [d.author for d in report.deferred] == ["plumb-projector"]


class TestNamespaces:
    def ghost(self) -> RawClaim:
        return readme_claim("exists", "true", symbol="py:pkg.m.ghost")

    def test_a_documented_name_the_closed_module_never_defined_is_projected_absent(self) -> None:
        h = Harness()
        h.commit(code=source(30), claims=[self.ghost()])
        assert h.present("plumb-projector") == {"false"}

    def test_the_module_opening_withdraws_the_projection_of_a_child_that_did_not_change(
        self,
    ) -> None:
        h = Harness()
        h.commit(code=source(30), claims=[self.ghost()])

        report = h.commit(code=source(30, dynamic=True))  # the README is untouched

        assert h.present("plumb-projector") == set()
        assert (report.projections_withdrawn, report.abstained) == (1, 1)

    def test_the_module_closing_again_restores_it(self) -> None:
        h = Harness()
        h.commit(code=source(30), claims=[self.ghost()])
        h.commit(code=source(30, dynamic=True))
        report = h.commit(code=source(30))
        assert h.present("plumb-projector") == {"false"} and report.projected == 1


class TestAbstentionCount:
    def test_a_documented_slot_the_code_cannot_confirm_is_counted(self) -> None:
        h = Harness()
        report = h.commit(code=source(30), claims=[readme_claim("returns.type", "int")])
        assert (report.projected, report.abstained) == (0, 1)
        assert h.present("plumb-projector") == set()


class TestStopsStating:
    """A fact the importer once stated and no longer can must be withdrawn, not left standing.

    Found on a real repository: a method gained a decorator the importer cannot see through,
    its old signature stayed in the KB as if current, and the projector reported a parameter
    that exists as missing -- seven false findings out of seven.
    """

    def decorated(self, default: int) -> bytes:
        return f"@vendor.wrap\ndef f(host, timeout={default}):\n    return host\n".encode()

    def test_the_old_signature_is_withdrawn_when_a_decorator_hides_it(self) -> None:
        h = started()
        report = h.commit(code=self.decorated(60))
        assert ("py:pkg.m.f", "signature_json") in h.kb.withdrawn
        assert "signature_json" not in (h.kb.symbols["py:pkg.m.f"])
        assert report.fields_withdrawn == 1

    def test_so_the_projection_goes_and_the_slot_is_an_honest_abstention(self) -> None:
        h = started()
        report = h.commit(code=self.decorated(60))
        assert h.present("plumb-projector") == set()
        assert h.present("plumb-readme") == {"30"}
        assert (report.projections_withdrawn, report.abstained) == (1, 1)

    def test_nothing_stale_is_projected_while_the_decorator_stays(self) -> None:
        h = started()
        h.commit(code=self.decorated(60))
        h.commit(code=self.decorated(99))
        assert h.present("plumb-projector") == set()

    def test_the_signature_comes_back_when_it_can_be_stated_again(self) -> None:
        h = started()
        h.commit(code=self.decorated(60))
        report = h.commit(code=source(60))
        assert h.present("plumb-projector") == {"60"}
        assert report.fields_withdrawn == 0

    def test_a_symbol_that_becomes_ambiguous_loses_its_details_too(self) -> None:
        h = started()
        h.commit(
            code=(
                b"try:\n    def f(host, timeout=30): ...\n"
                b"except ImportError:\n    def f(host, timeout=1): ...\n"
            )
        )
        assert h.kb.symbols["py:pkg.m.f"]["kind"] == "ambiguous"
        assert "signature_json" not in h.kb.symbols["py:pkg.m.f"]

    def test_required_fields_are_never_withdrawn(self) -> None:
        h = started()
        h.commit(code=self.decorated(60))
        assert {"kind", "present", "defined_at"} <= set(h.kb.symbols["py:pkg.m.f"])

    def test_an_unchanged_stated_field_is_not_withdrawn(self) -> None:
        h = started()
        report = h.commit(code=source(30))
        assert (h.kb.withdrawn, report.fields_withdrawn) == ([], 0)
