"""Behavior of the static-analysis code importer (PRD ING-1, DRF-3).

The importer emits positive L1 facts only, canonical already, and *abstains*
(emits nothing for the slot) whenever static analysis cannot be sure.
"""

from __future__ import annotations

from datetime import UTC, datetime
from textwrap import dedent

import pytest

from plumbline.adapters.python_code_importer import PythonCodeImporter
from plumbline.application.ports import CommitRef, RawClaim
from plumbline.domain import anchors

SHA = "abcdef0123456789abcdef0123456789abcdef01"
COMMIT = CommitRef(sha=SHA, committed_at=datetime(2024, 1, 1, tzinfo=UTC), changed_paths=())


def extract(
    source: str, path: str = "src/pkg/mod.py", **kwargs: bool
) -> dict[tuple[str, str], str]:
    """Run the importer over one file; return ``{(symbol, aspect): value}``."""
    importer = PythonCodeImporter("acme", "sdk", **kwargs)
    claims = importer.extract({path: dedent(source).encode()}, COMMIT)
    return {(c.symbol_key, c.aspect): c.raw_value for c in claims}


class TestSymbolsAndPaths:
    def test_module_function_class_and_method_exist(self) -> None:
        facts = extract("""
            def f(): ...
            class C:
                def m(self): ...
        """)
        for key in ("py:pkg.mod", "py:pkg.mod.f", "py:pkg.mod.C", "py:pkg.mod.C.m"):
            assert facts[(key, "exists")] == "true"

    def test_src_layout_prefix_is_stripped(self) -> None:
        assert ("py:pkg.mod", "exists") in extract("x = 1", "scenarios/demo/src/pkg/mod.py")

    def test_flat_layout_uses_the_path_as_is(self) -> None:
        assert ("py:pkg.mod", "exists") in extract("x = 1", "pkg/mod.py")

    def test_init_file_names_the_package(self) -> None:
        assert ("py:pkg", "exists") in extract("x = 1", "src/pkg/__init__.py")

    @pytest.mark.parametrize("path", ["README.md", "src/pkg/data.json", "src/9bad/mod.py"])
    def test_non_python_or_unimportable_paths_are_ignored(self, path: str) -> None:
        assert extract("x = 1", path) == {}

    def test_async_functions_are_functions(self) -> None:
        assert extract("async def f(a=1): ...")[("py:pkg.mod.f", "param.a.default")] == "1"

    def test_nested_functions_are_not_addressable(self) -> None:
        facts = extract("""
            def outer():
                def inner(): ...
        """)
        assert ("py:pkg.mod.outer.inner", "exists") not in facts


class TestSignatures:
    def test_param_names_in_declaration_order_with_star_forms(self) -> None:
        facts = extract("def f(a, b, /, c, *args, d, e=1, **kw): ...")
        assert facts[("py:pkg.mod.f", "param_names")] == '["a","b","c","*args","d","e","**kw"]'

    def test_only_named_params_get_exists_facts(self) -> None:
        facts = extract("def f(a, *args, **kw): ...")
        assert ("py:pkg.mod.f", "param.a.exists") in facts
        assert ("py:pkg.mod.f", "param.args.exists") not in facts
        assert ("py:pkg.mod.f", "param.kw.exists") not in facts

    def test_methods_drop_self_and_cls_but_not_staticmethod_args(self) -> None:
        facts = extract("""
            class C:
                def m(self, a): ...
                @classmethod
                def c(cls, a): ...
                @staticmethod
                def s(a, b): ...
        """)
        assert facts[("py:pkg.mod.C.m", "param_names")] == '["a"]'
        assert facts[("py:pkg.mod.C.c", "param_names")] == '["a"]'
        assert facts[("py:pkg.mod.C.s", "param_names")] == '["a","b"]'

    @pytest.mark.parametrize(
        ("default", "expected"),
        [
            ("30", "30"),
            ("-1", "-1"),
            ('"utf-8"', "'utf-8'"),
            ("None", "None"),
            ("(1, 2)", "(1, 2)"),
        ],
    )
    def test_literal_defaults_are_canonical(self, default: str, expected: str) -> None:
        facts = extract(f"def f(x={default}): ...")
        assert facts[("py:pkg.mod.f", "param.x.default")] == expected

    def test_keyword_only_defaults_are_found(self) -> None:
        facts = extract("def f(*, a, b=2): ...")
        assert ("py:pkg.mod.f", "param.a.default") not in facts
        assert facts[("py:pkg.mod.f", "param.b.default")] == "2"

    def test_non_literal_default_abstains(self) -> None:
        facts = extract("TIMEOUT = 5\ndef f(x=TIMEOUT, y=[]): ...")
        assert ("py:pkg.mod.f", "param.x.default") not in facts
        assert facts[("py:pkg.mod.f", "param.x.exists")] == "true"

    def test_annotations_are_canonical(self) -> None:
        facts = extract("def f(a: int | None, b: 'Foo', c: typing.List[int]) -> str: ...")
        assert facts[("py:pkg.mod.f", "param.a.type")] == "None | int"
        assert facts[("py:pkg.mod.f", "param.b.type")] == "Foo"
        assert facts[("py:pkg.mod.f", "param.c.type")] == "List[int]"
        assert facts[("py:pkg.mod.f", "returns.type")] == "str"

    def test_optional_and_union_normalize_to_pep_604(self) -> None:
        facts = extract("""
            from typing import Optional, Union
            def f(a: Optional[int], b: Union[str, int, None], c: typing.Optional[str]): ...
        """)
        assert facts[("py:pkg.mod.f", "param.a.type")] == "None | int"
        assert facts[("py:pkg.mod.f", "param.b.type")] == "None | int | str"
        assert facts[("py:pkg.mod.f", "param.c.type")] == "None | str"

    def test_unannotated_parameters_have_no_type_fact(self) -> None:
        assert ("py:pkg.mod.f", "param.a.type") not in extract("def f(a): ...")


class TestRaises:
    def test_direct_raises_are_recorded_once_each(self) -> None:
        facts = extract("""
            def f(x):
                if x:
                    raise KeyError(x)
                raise json.JSONDecodeError
                raise KeyError
        """)
        assert facts[("py:pkg.mod.f", "raises.KeyError")] == "true"
        assert facts[("py:pkg.mod.f", "raises.json.JSONDecodeError")] == "true"

    def test_never_projects_absence(self) -> None:
        facts = extract("def f(): ...")
        assert not [k for k in facts if k[1].startswith("raises.")]

    def test_nested_functions_and_reraises_do_not_count(self) -> None:
        facts = extract("""
            def f():
                def inner():
                    raise ValueError
                try:
                    pass
                except Exception as exc:
                    raise exc
                except KeyError:
                    raise
        """)
        assert not [k for k in facts if k[1].startswith("raises.")]


class TestDeprecation:
    @pytest.mark.parametrize(
        "decorator",
        [
            "@deprecated",
            "@deprecated('x')",
            "@warnings.deprecated('x')",
            "@typing_extensions.deprecated",
        ],
    )
    def test_decorator_marks_deprecated(self, decorator: str) -> None:
        facts = extract(f"{decorator}\ndef f(): ...")
        assert facts[("py:pkg.mod.f", "deprecated")] == "true"

    def test_deprecation_warning_at_entry(self) -> None:
        facts = extract('''
            def f():
                """Doc."""
                warnings.warn("old", DeprecationWarning)
                return 1
            def g():
                warn("old", category=DeprecationWarning, stacklevel=2)
        ''')
        assert facts[("py:pkg.mod.f", "deprecated")] == "true"
        assert facts[("py:pkg.mod.g", "deprecated")] == "true"

    def test_unmarked_function_is_not_deprecated(self) -> None:
        facts = extract("""
            def f():
                return 1
                warnings.warn("late", DeprecationWarning)
            def g():
                warnings.warn("other", UserWarning)
        """)
        assert facts[("py:pkg.mod.f", "deprecated")] == "false"
        assert facts[("py:pkg.mod.g", "deprecated")] == "false"

    def test_other_calls_at_entry_are_not_deprecation_warnings(self) -> None:
        facts = extract("def f():\n    log('old', DeprecationWarning)\n")
        assert facts[("py:pkg.mod.f", "deprecated")] == "false"

    def test_classes_can_be_deprecated(self) -> None:
        assert extract("@deprecated('x')\nclass C: ...")[("py:pkg.mod.C", "deprecated")] == "true"


class TestAbstention:
    def test_duplicate_definitions_abstain_entirely(self) -> None:
        facts = extract("""
            try:
                def f(a=1): ...
            except ImportError:
                def f(a=2): ...
            def g(): ...
        """)
        assert not [k for k in facts if k[0] == "py:pkg.mod.f"]
        assert ("py:pkg.mod.g", "exists") in facts

    def test_overload_stubs_are_not_definitions(self) -> None:
        facts = extract("""
            @overload
            def f(a: int) -> int: ...
            @overload
            def f(a: str) -> str: ...
            def f(a): ...
        """)
        assert facts[("py:pkg.mod.f", "param_names")] == '["a"]'

    def test_definitions_inside_conditionals_are_found_once(self) -> None:
        assert ("py:pkg.mod.f", "exists") in extract("if X:\n    def f(): ...")

    @pytest.mark.parametrize("source", ["def (:", "x = (", "\x00"])
    def test_unparseable_source_yields_nothing(self, source: str) -> None:
        assert extract(source) == {}

    def test_dynamic_module_asserts_nothing_about_unseen_names(self) -> None:
        facts = extract("def __getattr__(name): raise AttributeError(name)")
        assert ("py:pkg.mod.fancy", "exists") not in facts


class TestPrivacy:
    SOURCE = """
        def public(): ...
        def _private(): ...
        class _Hidden:
            def method(self): ...
        class Public:
            def _helper(self): ...
            def __init__(self): ...
    """

    def test_private_symbols_are_skipped_by_default(self) -> None:
        keys = {k[0] for k in extract(self.SOURCE)}
        assert "py:pkg.mod.public" in keys
        assert "py:pkg.mod.Public.__init__" in keys  # dunders are public
        assert (
            not {
                "py:pkg.mod._private",
                "py:pkg.mod._Hidden",
                "py:pkg.mod._Hidden.method",
                "py:pkg.mod.Public._helper",
            }
            & keys
        )

    def test_include_private_emits_them(self) -> None:
        keys = {k[0] for k in extract(self.SOURCE, include_private=True)}
        assert {"py:pkg.mod._private", "py:pkg.mod.Public._helper"} <= keys


class TestClaimShape:
    def claims(self) -> list[RawClaim]:
        src = b"def f(a=1):\n    return a\n"
        return PythonCodeImporter("acme", "sdk").extract({"src/pkg/mod.py": src}, COMMIT)

    def test_anchors_pin_the_commit_and_the_definition_lines(self) -> None:
        by_aspect = {c.aspect: c for c in self.claims() if c.symbol_key == "py:pkg.mod.f"}
        anchor = anchors.parse(by_aspect["exists"].anchor_uri)
        assert (anchor.owner, anchor.repo, anchor.commit_sha) == ("acme", "sdk", SHA)
        assert (anchor.path, anchor.line_start, anchor.line_end) == ("src/pkg/mod.py", 1, 2)

    def test_parameter_facts_anchor_to_the_parameter_line(self) -> None:
        by_aspect = {c.aspect: c for c in self.claims() if c.symbol_key == "py:pkg.mod.f"}
        anchor = anchors.parse(by_aspect["param.a.default"].anchor_uri)
        assert (anchor.line_start, anchor.line_end) == (1, 1)

    def test_static_analysis_has_full_extraction_confidence(self) -> None:
        assert {c.confidence for c in self.claims()} == {1.0}

    def test_every_claim_carries_a_rationale(self) -> None:
        assert all(c.rationale for c in self.claims())

    def test_output_is_sorted_and_input_order_independent(self) -> None:
        a = b"def f(): ...\n"
        b = b"def g(): ...\n"
        importer = PythonCodeImporter("acme", "sdk")
        one = importer.extract({"src/pkg/a.py": a, "src/pkg/b.py": b}, COMMIT)
        two = importer.extract({"src/pkg/b.py": b, "src/pkg/a.py": a}, COMMIT)
        assert one == two
        assert one == sorted(one, key=lambda c: (c.symbol_key, c.aspect))
