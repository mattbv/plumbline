"""The projector's decisions (ADR-0007), against a fake KB: what to withdraw, what to state."""

from __future__ import annotations

from datetime import UTC, datetime

from plumbline.application.ports import CommitRef, PresentClaim
from plumbline.application.projection import PROJECTOR_PRINCIPAL, DocChanges, Projector
from plumbline.domain import anchors

SHA = "abcdef0123456789abcdef0123456789abcdef01"
COMMIT = CommitRef(SHA, datetime(2026, 1, 1, tzinfo=UTC), ())
SIG = '{"param_names":["host","timeout"],"params":{"timeout":{"default":"30"}},"v":1}'
FACT = "py:pkg.m.f#param.timeout.default"
NO_CHANGES = DocChanges(frozenset(), {})


class FakeKB:
    def __init__(self) -> None:
        self.symbols: dict[str, dict[str, str]] = {
            "py:pkg": {
                "kind": "module",
                "present": "true",
                "namespace_closed": "true",
                "defined_at": "pkg/__init__.py",
            },
            "py:pkg.m": {
                "kind": "module",
                "present": "true",
                "namespace_closed": "true",
                "defined_at": "pkg/m.py",
            },
            "py:pkg.m.f": {
                "kind": "function",
                "present": "true",
                "defined_at": "pkg/m.py",
                "signature_json": SIG,
            },
        }
        self.claims: dict[str, list[PresentClaim]] = {}

    def symbol_fields(self, key: str) -> dict[str, str] | None:
        return self.symbols.get(key)

    def claims_on(self, fact_key: str) -> list[PresentClaim]:
        return list(self.claims.get(fact_key, []))


def doc(claim_id: str = "d1", value: str = "30", author: str = "plumb-readme") -> PresentClaim:
    return PresentClaim(claim_id, author, value, "README.md")


def projection(value: str = "30", path: str = "pkg/m.py", claim_id: str = "p1") -> PresentClaim:
    return PresentClaim(claim_id, PROJECTOR_PRINCIPAL, value, path)


def plan(kb: FakeKB, facts: list[str], changes: DocChanges = NO_CHANGES):  # type: ignore[no-untyped-def]
    return Projector(kb, "o", "r").plan(COMMIT, facts, changes)  # type: ignore[arg-type]


class TestWhatIsProjected:
    def test_a_documented_slot_gets_the_codes_value(self) -> None:
        kb = FakeKB()
        kb.claims[FACT] = [doc()]
        [step] = plan(kb, [FACT]).steps
        [claim] = step.assert_
        assert (claim.symbol_key, claim.aspect, claim.raw_value) == (
            "py:pkg.m.f",
            "param.timeout.default",
            "30",
        )
        assert step.retract == []

    def test_an_undocumented_slot_gets_nothing(self) -> None:
        """The KB grows with the documentation, not with the code (DRF-2)."""
        assert plan(FakeKB(), [FACT]).steps == []

    def test_an_unowned_aspect_is_left_alone(self) -> None:
        kb = FakeKB()
        kb.claims["py:pkg.m.f#added_in"] = [doc(value="1.0")]
        assert plan(kb, ["py:pkg.m.f#added_in"]).steps == []

    def test_a_claim_about_to_be_written_counts_as_documentation(self) -> None:
        """The slot must be projected in the same commit its first claim arrives."""
        steps = plan(FakeKB(), [FACT], DocChanges(frozenset(), {FACT: ["30"]})).steps
        assert len(steps) == 1 and steps[0].assert_

    def test_the_last_claim_leaving_withdraws_the_projection(self) -> None:
        kb = FakeKB()
        kb.claims[FACT] = [doc("d1"), projection()]
        [step] = plan(kb, [FACT], DocChanges(frozenset({"d1"}), {FACT: []})).steps
        assert [c.claim_id for c in step.retract] == ["p1"] and step.assert_ == []

    def test_another_remaining_claim_keeps_the_projection(self) -> None:
        kb = FakeKB()
        kb.claims[FACT] = [doc("d1"), doc("d2", author="plumb-docs"), projection()]
        assert plan(kb, [FACT], DocChanges(frozenset({"d1"}), {FACT: []})).steps == []


class TestChangingTheProjection:
    def test_nothing_is_done_when_the_projection_is_already_right(self) -> None:
        kb = FakeKB()
        kb.claims[FACT] = [doc(), projection()]
        assert plan(kb, [FACT]).steps == []

    def test_a_changed_value_withdraws_the_old_projection_and_states_the_new_one(self) -> None:
        kb = FakeKB()
        kb.claims[FACT] = [doc(), projection(value="45")]
        [step] = plan(kb, [FACT]).steps
        assert [c.value for c in step.retract] == ["45"]
        assert [c.raw_value for c in step.assert_] == ["30"]

    def test_a_moved_definition_is_a_new_identity(self) -> None:
        """Identity is (fact, author, path, value): the path moved, so it is re-stated."""
        kb = FakeKB()
        kb.claims[FACT] = [doc(), projection(path="old/m.py")]
        [step] = plan(kb, [FACT]).steps
        assert [c.path for c in step.retract] == ["old/m.py"]
        assert [anchors.parse(c.anchor_uri).path for c in step.assert_] == ["pkg/m.py"]

    def test_an_unprovable_value_withdraws_the_stale_projection(self) -> None:
        kb = FakeKB()
        kb.claims[FACT] = [doc(), projection()]
        kb.symbols["py:pkg.m.f"]["signature_json"] = (
            '{"param_names":["host","timeout"],"v":1}'  # default gone
        )
        [step] = plan(kb, [FACT]).steps
        assert [c.claim_id for c in step.retract] == ["p1"] and step.assert_ == []


class TestAbstention:
    def test_an_unprovable_slot_is_counted_not_projected(self) -> None:
        kb = FakeKB()
        kb.symbols["py:pkg.m.f"].pop("signature_json")
        kb.claims[FACT] = [doc()]
        result = plan(kb, [FACT])
        assert (result.steps, result.abstained) == ([], 1)

    def test_an_undocumented_slot_is_not_an_abstention(self) -> None:
        assert plan(FakeKB(), [FACT]).abstained == 0

    def test_a_symbol_the_kb_never_saw_in_an_open_module_abstains(self) -> None:
        kb = FakeKB()
        kb.symbols["py:pkg.m"]["namespace_closed"] = "false"
        kb.claims["py:pkg.m.ghost#exists"] = [doc(value="true")]
        assert plan(kb, ["py:pkg.m.ghost#exists"]).abstained == 1

    def test_a_symbol_the_kb_never_saw_in_a_closed_module_is_provably_absent(self) -> None:
        kb = FakeKB()
        kb.claims["py:pkg.m.ghost#exists"] = [doc(value="true")]
        [step] = plan(kb, ["py:pkg.m.ghost#exists"]).steps
        [claim] = step.assert_
        assert claim.raw_value == "false"
        assert anchors.parse(claim.anchor_uri).path == "pkg/m.py"  # the module it would live in

    def test_an_unknown_enclosing_class_means_not_provable(self) -> None:
        kb = FakeKB()
        kb.claims["py:pkg.m.Ghost.x#exists"] = [doc(value="true")]
        assert plan(kb, ["py:pkg.m.Ghost.x#exists"]).abstained == 1


class TestClaimShape:
    def test_provenance_names_the_definition_at_the_commit(self) -> None:
        kb = FakeKB()
        kb.claims[FACT] = [doc()]
        [claim] = plan(kb, [FACT]).steps[0].assert_
        anchor = anchors.parse(claim.anchor_uri)
        assert (anchor.owner, anchor.repo, anchor.commit_sha) == ("o", "r", SHA)
        assert (anchor.path, anchor.symbol) == ("pkg/m.py", "pkg.m.f")

    def test_confidence_is_certain_and_the_rationale_names_the_source_field(self) -> None:
        kb = FakeKB()
        kb.claims[FACT] = [doc()]
        [claim] = plan(kb, [FACT]).steps[0].assert_
        assert claim.confidence == 1.0
        assert claim.rationale == "projection of signature_json [drift-projector/1]"

    def test_exists_and_deprecated_cite_their_own_fields(self) -> None:
        kb = FakeKB()
        kb.symbols["py:pkg.m.f"]["is_deprecated"] = "false"
        kb.claims["py:pkg.m.f#exists"] = [doc(value="true")]
        kb.claims["py:pkg.m.f#deprecated"] = [doc(value="true")]
        by_aspect = {
            s.assert_[0].aspect: s.assert_[0]
            for s in plan(kb, ["py:pkg.m.f#exists", "py:pkg.m.f#deprecated"]).steps
        }
        assert by_aspect["exists"].rationale == "projection of present [drift-projector/1]"
        assert (
            by_aspect["deprecated"].rationale == "projection of is_deprecated [drift-projector/1]"
        )

    def test_steps_are_ordered_by_fact_key(self) -> None:
        kb = FakeKB()
        for key in ("py:pkg.m.f#exists", "py:pkg.m.f#deprecated"):
            kb.claims[key] = [doc(value="true")]
        kb.symbols["py:pkg.m.f"]["is_deprecated"] = "false"
        steps = plan(kb, ["py:pkg.m.f#exists", "py:pkg.m.f#deprecated"]).steps
        assert [s.fact_key for s in steps] == sorted(s.fact_key for s in steps)


TYPED_SIG = (
    '{"param_names":["host","timeout","mode"],"params":{"timeout":{"type":"int"},'
    '"mode":{"type":"JustifyMethod"},"host":{"type":"None | str"}},"returns":"int","v":1}'
)
TYPE_FACT = "py:pkg.m.f#param.timeout.type"
ALIAS_FACT = "py:pkg.m.f#param.mode.type"
NULLABLE_FACT = "py:pkg.m.f#param.host.type"


def typed_kb() -> FakeKB:
    kb = FakeKB()
    kb.symbols["py:pkg.m.f"]["signature_json"] = TYPED_SIG
    return kb


class TestTypesThatCannotBeProvenDifferent:
    """A type disagreement is stated only when it is provable (ADR-0007 Amendments 3 and 4)."""

    def test_a_provable_disagreement_is_stated(self) -> None:
        kb = typed_kb()
        kb.claims[TYPE_FACT] = [doc(value="str")]
        [step] = plan(kb, [TYPE_FACT]).steps
        assert [c.raw_value for c in step.assert_] == ["int"]

    def test_docs_that_allow_none_where_the_code_does_not_abstain(self) -> None:
        kb = typed_kb()
        kb.claims[TYPE_FACT] = [doc(value="None | int")]
        result = plan(kb, [TYPE_FACT])
        assert result.steps == [] and result.abstained == 1

    def test_docs_that_omit_none_are_stated_against(self) -> None:
        """PRD §14 #10."""
        kb = typed_kb()
        kb.claims[NULLABLE_FACT] = [doc(value="str")]
        [step] = plan(kb, [NULLABLE_FACT]).steps
        assert [c.raw_value for c in step.assert_] == ["None | str"]

    def test_a_name_that_may_be_an_alias_abstains(self) -> None:
        kb = typed_kb()
        kb.claims[ALIAS_FACT] = [doc(value="str")]
        result = plan(kb, [ALIAS_FACT])
        assert result.steps == [] and result.abstained == 1

    def test_agreement_is_corroborated(self) -> None:
        kb = typed_kb()
        kb.claims[ALIAS_FACT] = [doc(value="JustifyMethod")]
        [step] = plan(kb, [ALIAS_FACT]).steps
        assert [c.raw_value for c in step.assert_] == ["JustifyMethod"]

    def test_a_claim_about_to_be_written_is_compared_too(self) -> None:
        """The first docstring that arrives is the one that must not be disputed."""
        result = plan(typed_kb(), [ALIAS_FACT], DocChanges(frozenset(), {ALIAS_FACT: ["str"]}))
        assert result.steps == [] and result.abstained == 1

    def test_a_projection_is_withdrawn_when_the_docs_change_to_something_unprovable(self) -> None:
        kb = typed_kb()
        kb.claims[TYPE_FACT] = [doc("d2", value="None | int"), projection(value="int")]
        [step] = plan(kb, [TYPE_FACT]).steps
        assert [c.claim_id for c in step.retract] == ["p1"] and step.assert_ == []

    def test_a_claim_about_to_be_withdrawn_is_not_compared(self) -> None:
        """Only the docs that remain decide: the one leaving is the provable one."""
        kb = typed_kb()
        kb.claims[TYPE_FACT] = [
            doc("d1", value="str"),
            doc("d2", author="plumb-docs", value="None | int"),
        ]
        result = plan(kb, [TYPE_FACT], DocChanges(frozenset({"d1"}), {TYPE_FACT: []}))
        assert result.steps == [] and result.abstained == 1

    def test_defaults_are_never_subject_to_this_rule(self) -> None:
        kb = FakeKB()
        kb.claims[FACT] = [doc(value="45")]
        [step] = plan(kb, [FACT]).steps
        assert [c.raw_value for c in step.assert_] == ["30"]


SENTINEL_SIG = '{"param_names":["host","engine"],"params":{"engine":{"default":"None"}},"v":1}'
SENTINEL_FACT = "py:pkg.m.f#param.engine.default"


class TestNoneDefaultIsASentinel:
    """ADR-0007 Amendment 5 D: a None default behind a documented effective default abstains."""

    def kb(self) -> FakeKB:
        kb = FakeKB()
        kb.symbols["py:pkg.m.f"]["signature_json"] = SENTINEL_SIG
        return kb

    def test_a_documented_concrete_default_behind_none_abstains(self) -> None:
        kb = self.kb()
        kb.claims[SENTINEL_FACT] = [doc(value="'numexpr'")]
        result = plan(kb, [SENTINEL_FACT])
        assert result.steps == [] and result.abstained == 1

    def test_agreement_on_none_is_corroborated(self) -> None:
        kb = self.kb()
        kb.claims[SENTINEL_FACT] = [doc(value="None")]
        [step] = plan(kb, [SENTINEL_FACT]).steps
        assert [c.raw_value for c in step.assert_] == ["None"]

    def test_a_claim_about_to_be_written_is_compared_too(self) -> None:
        result = plan(
            self.kb(), [SENTINEL_FACT], DocChanges(frozenset(), {SENTINEL_FACT: ["'numexpr'"]})
        )
        assert result.steps == [] and result.abstained == 1

    def test_a_projection_is_withdrawn_when_the_docs_become_a_concrete_default(self) -> None:
        kb = self.kb()
        kb.claims[SENTINEL_FACT] = [doc("d2", value="'numexpr'"), projection(value="None")]
        [step] = plan(kb, [SENTINEL_FACT]).steps
        assert [c.claim_id for c in step.retract] == ["p1"] and step.assert_ == []

    def test_a_concrete_code_default_against_docs_saying_none_is_still_reported(self) -> None:
        kb = FakeKB()  # the standard fixture has a concrete default of 30
        kb.claims[FACT] = [doc(value="None")]
        [step] = plan(kb, [FACT]).steps
        assert [c.raw_value for c in step.assert_] == ["30"]

    def test_types_are_not_affected(self) -> None:
        kb = typed_kb()
        kb.claims[TYPE_FACT] = [doc(value="str")]
        [step] = plan(kb, [TYPE_FACT]).steps
        assert [c.raw_value for c in step.assert_] == ["int"]
