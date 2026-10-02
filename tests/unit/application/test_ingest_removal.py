"""Removal and key ownership in IngestOneCommit (ADR-0005), against fakes.

Every uncertain case must leave the KB as it was: that can delay a true drift
report but never invent one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from plumbline.application.ports import CommitRef, RawClaim
from plumbline.application.symbol_facts import KeyConflict
from plumbline.application.use_cases.ingest import IngestOneCommit
from plumbline.domain import anchors
from tests.unit.application.test_ingest import FakeKnowledgeBase

T0 = datetime(2026, 1, 1, tzinfo=UTC)
SHA = "abcdef0123456789abcdef0123456789abcdef01"


def _claims(symbol: str, kind: str, path: str, *, detail: bool = True) -> list[RawClaim]:
    """The importer-style claims for one symbol defined in ``path``."""
    anchor = f"repo://o/r@{SHA}/{path}#L1-L2"
    claims = [
        RawClaim(symbol, "exists", "true", anchor, 1.0, "t"),
        RawClaim(symbol, "kind", kind, anchor, 1.0, "t"),
    ]
    if detail and kind in ("function", "method", "class"):
        claims.append(RawClaim(symbol, "deprecated", "false", anchor, 1.0, "t"))
    return claims


class Importer:
    """Returns whatever claims the current test staged."""

    def __init__(self) -> None:
        self.claims: list[RawClaim] = []

    def extract(self, files: dict[str, bytes], commit: CommitRef) -> list[RawClaim]:
        return list(self.claims)


class Repo:
    def __init__(self) -> None:
        self.present: set[str] = set()

    def first_parent_history(self, *, since: datetime | None = None) -> list[CommitRef]:
        return []

    def read_file_at(self, path: str, commit_sha: str) -> bytes:
        if path not in self.present:
            raise FileNotFoundError(path)
        return b""


class Harness:
    def __init__(self) -> None:
        self.kb = FakeKnowledgeBase()
        self.importer = Importer()
        self.repo = Repo()
        self.clock = T0
        self.use_case = IngestOneCommit(
            repo=self.repo,
            code_importer=self.importer,
            doc_importers=(),
            kb=self.kb,
            repo_slug="o/r",
        )

    def commit(self, changed: list[str], claims: list[RawClaim], exists: list[str] | None = None):  # type: ignore[no-untyped-def]
        """Apply a commit: ``changed`` paths, of which ``exists`` (default: all) are readable."""
        self.repo.present = set(changed if exists is None else exists)
        self.importer.claims = claims
        self.clock += timedelta(hours=1)
        ref = CommitRef(sha=SHA, committed_at=self.clock, changed_paths=tuple(changed))
        return self.use_case.run(ref)

    def present(self, symbol: str) -> str | None:
        return (self.kb.symbols.get(symbol) or {}).get("present")


def _module(path: str, name: str) -> list[RawClaim]:
    return _claims(f"py:{name}", "module", path)


def _file_with(path: str, module: str, *functions: str) -> list[RawClaim]:
    claims = _module(path, module)
    for fn in functions:
        claims += _claims(f"py:{module}.{fn}", "function", path)
    return claims


class TestRemoval:
    def test_a_symbol_that_leaves_a_still_analyzed_file_is_marked_not_present(self) -> None:
        h = Harness()
        h.commit(["a.py"], _file_with("a.py", "a", "f", "g"))
        report = h.commit(["a.py"], _file_with("a.py", "a", "f"))

        assert report.removed == ("py:a.g",)
        assert (h.present("py:a.f"), h.present("py:a.g")) == ("true", "false")

    def test_the_removal_is_a_write_at_the_commit_time_anchored_to_that_commit(self) -> None:
        h = Harness()
        h.commit(["a.py"], _file_with("a.py", "a", "g"))
        h.commit(["a.py"], _file_with("a.py", "a"))

        *_, last = [w for w in h.kb.writes if w[1] == "present"]
        key, _field, value, when, source = last
        assert (key, value, when) == ("py:a.g", "false", h.clock)
        anchor = anchors.parse(source)
        assert (anchor.owner, anchor.repo, anchor.commit_sha) == ("o", "r", SHA)
        assert (anchor.path, anchor.line_start, anchor.line_end) == ("a.py", 1, 1)

    def test_other_fields_of_a_removed_symbol_are_left_alone(self) -> None:
        h = Harness()
        h.commit(["a.py"], _file_with("a.py", "a", "g"))
        before = dict(h.kb.symbols["py:a.g"])
        h.commit(["a.py"], _file_with("a.py", "a"))
        assert {k: v for k, v in h.kb.symbols["py:a.g"].items() if k != "present"} == {
            k: v for k, v in before.items() if k != "present"
        }

    def test_deleting_a_file_removes_everything_it_defined(self) -> None:
        h = Harness()
        h.commit(["a.py"], _file_with("a.py", "a", "f", "g"))
        report = h.commit(["a.py"], [], exists=[])

        assert set(report.removed) == {"py:a", "py:a.f", "py:a.g"}
        assert {h.present(k) for k in ("py:a", "py:a.f", "py:a.g")} == {"false"}

    def test_a_rename_removes_the_old_keys_and_adds_the_new_ones(self) -> None:
        h = Harness()
        h.commit(["old.py"], _file_with("old.py", "old", "f"))
        report = h.commit(["old.py", "new.py"], _file_with("new.py", "new", "f"), exists=["new.py"])

        assert set(report.removed) == {"py:old", "py:old.f"}
        assert (h.present("py:new.f"), h.present("py:old.f")) == ("true", "false")

    def test_a_symbol_that_comes_back_is_present_again(self) -> None:
        h = Harness()
        h.commit(["a.py"], _file_with("a.py", "a", "f"))
        h.commit(["a.py"], _file_with("a.py", "a"))
        report = h.commit(["a.py"], _file_with("a.py", "a", "f"))

        assert h.present("py:a.f") == "true"
        assert report.removed == ()

    def test_a_removed_symbol_is_not_removed_twice(self) -> None:
        h = Harness()
        h.commit(["a.py"], _file_with("a.py", "a", "f"))
        h.commit(["a.py"], _file_with("a.py", "a"))
        again = h.commit(["a.py"], _file_with("a.py", "a"))
        assert again.removed == () and again.written == 0

    def test_files_that_did_not_change_are_never_inspected_for_removal(self) -> None:
        h = Harness()
        h.commit(["a.py", "b.py"], _file_with("a.py", "a", "f") + _file_with("b.py", "b", "g"))
        report = h.commit(["a.py"], _file_with("a.py", "a", "f"))
        assert report.removed == () and h.present("py:b.g") == "true"


class TestAbstentionIsNotRemoval:
    def test_a_file_that_stops_parsing_leaves_its_symbols_untouched_and_is_reported(self) -> None:
        h = Harness()
        h.commit(["a.py"], _file_with("a.py", "a", "f"))
        writes = len(h.kb.writes)

        report = h.commit(["a.py"], [])  # the file exists, but yields nothing

        assert report.removed == () and report.unanalyzed == ("a.py",)
        assert len(h.kb.writes) == writes
        assert h.present("py:a.f") == "true"

    def test_non_code_files_with_no_known_symbols_are_not_reported(self) -> None:
        h = Harness()
        assert h.commit(["README.md"], []).unanalyzed == ()

    def test_a_name_that_becomes_ambiguous_is_not_removed(self) -> None:
        h = Harness()
        h.commit(["a.py"], _file_with("a.py", "a", "f"))
        ambiguous = _module("a.py", "a") + _claims("py:a.f", "ambiguous", "a.py")
        report = h.commit(["a.py"], ambiguous)

        assert report.removed == ()
        assert h.kb.symbols["py:a.f"]["kind"] == "ambiguous"
        assert h.present("py:a.f") == "true"

    def test_members_of_a_class_that_becomes_ambiguous_are_not_removed(self) -> None:
        h = Harness()
        h.commit(
            ["a.py"],
            _module("a.py", "a")
            + _claims("py:a.C", "class", "a.py")
            + _claims("py:a.C.m", "method", "a.py"),
        )
        report = h.commit(["a.py"], _module("a.py", "a") + _claims("py:a.C", "ambiguous", "a.py"))

        assert report.removed == ()
        assert h.present("py:a.C.m") == "true"

    def test_members_of_a_class_that_is_really_gone_are_removed(self) -> None:
        h = Harness()
        h.commit(
            ["a.py"],
            _module("a.py", "a")
            + _claims("py:a.C", "class", "a.py")
            + _claims("py:a.C.m", "method", "a.py"),
        )
        report = h.commit(["a.py"], _module("a.py", "a"))
        assert set(report.removed) == {"py:a.C", "py:a.C.m"}

    def test_an_unambiguous_again_symbol_resumes_normal_diffing(self) -> None:
        h = Harness()
        h.commit(["a.py"], _module("a.py", "a") + _claims("py:a.f", "ambiguous", "a.py"))
        h.commit(["a.py"], _file_with("a.py", "a", "f"))
        assert h.kb.symbols["py:a.f"]["kind"] == "function"


class TestOwnership:
    def test_a_module_takes_over_a_key_from_an_import_bound_attribute(self) -> None:
        h = Harness()
        # `from . import sub` in __init__.py arrives first: an attribute named like the module.
        h.commit(
            ["pkg/__init__.py"],
            _module("pkg/__init__.py", "pkg")
            + _claims("py:pkg.sub", "attribute", "pkg/__init__.py"),
        )
        report = h.commit(["pkg/sub.py"], _module("pkg/sub.py", "pkg.sub"))

        assert (h.kb.symbols["py:pkg.sub"]["kind"], h.kb.symbols["py:pkg.sub"]["defined_at"]) == (
            "module",
            "pkg/sub.py",
        )
        assert report.conflicts == ()

    def test_an_attribute_cannot_take_a_key_from_a_module(self) -> None:
        h = Harness()
        h.commit(["pkg/sub.py"], _module("pkg/sub.py", "pkg.sub"))
        report = h.commit(
            ["pkg/__init__.py"],
            _module("pkg/__init__.py", "pkg")
            + _claims("py:pkg.sub", "attribute", "pkg/__init__.py"),
        )

        assert h.kb.symbols["py:pkg.sub"]["kind"] == "module"
        assert h.kb.symbols["py:pkg.sub"]["defined_at"] == "pkg/sub.py"
        assert report.conflicts == (KeyConflict("py:pkg.sub", "pkg/sub.py", "pkg/__init__.py"),)

    def test_re_ingesting_the_importing_file_does_not_flip_the_owner(self) -> None:
        h = Harness()
        h.commit(["pkg/sub.py"], _module("pkg/sub.py", "pkg.sub"))
        alias = _module("pkg/__init__.py", "pkg") + _claims(
            "py:pkg.sub", "attribute", "pkg/__init__.py"
        )
        for _ in range(3):
            h.commit(["pkg/__init__.py"], alias)
        assert h.kb.symbols["py:pkg.sub"]["defined_at"] == "pkg/sub.py"

    def test_a_tie_keeps_the_first_writer(self) -> None:
        h = Harness()
        h.commit(["a/x.py"], _claims("py:m.f", "function", "a/x.py") + _module("a/x.py", "a.x"))
        report = h.commit(
            ["b/x.py"], _claims("py:m.f", "function", "b/x.py") + _module("b/x.py", "b.x")
        )

        assert h.kb.symbols["py:m.f"]["defined_at"] == "a/x.py"
        assert report.conflicts == (KeyConflict("py:m.f", "a/x.py", "b/x.py"),)

    def test_a_key_is_free_once_its_owner_file_is_deleted(self) -> None:
        """A flat->src layout move keeps the key but changes the path."""
        h = Harness()
        h.commit(["pkg/m.py"], _file_with("pkg/m.py", "pkg.m", "f"))
        report = h.commit(
            ["pkg/m.py", "src/pkg/m.py"],
            _file_with("src/pkg/m.py", "pkg.m", "f"),
            exists=["src/pkg/m.py"],
        )

        assert h.kb.symbols["py:pkg.m.f"]["defined_at"] == "src/pkg/m.py"
        assert h.present("py:pkg.m.f") == "true"
        assert report.removed == () and report.conflicts == ()

    def test_a_key_is_free_once_its_owner_was_reanalyzed_without_it(self) -> None:
        h = Harness()
        h.commit(
            ["a/x.py"], _module("a/x.py", "a.x") + _claims("py:shared.f", "function", "a/x.py")
        )
        # a/x.py is re-analyzed and no longer defines `shared.f`; b/x.py now does.
        report = h.commit(
            ["a/x.py", "b/x.py"],
            _module("a/x.py", "a.x")
            + _module("b/x.py", "b.x")
            + _claims("py:shared.f", "function", "b/x.py"),
        )

        assert h.kb.symbols["py:shared.f"]["defined_at"] == "b/x.py"
        assert h.present("py:shared.f") == "true"
        assert report.removed == () and report.conflicts == ()

    def test_a_removed_symbol_can_be_claimed_by_a_different_path(self) -> None:
        h = Harness()
        h.commit(["a.py"], _file_with("a.py", "a", "f"))
        h.commit(["a.py"], _file_with("a.py", "a"))
        h.commit(["b.py"], _claims("py:a.f", "function", "b.py") + _module("b.py", "b"))
        assert (h.kb.symbols["py:a.f"]["defined_at"], h.present("py:a.f")) == ("b.py", "true")
