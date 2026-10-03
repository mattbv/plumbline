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
    def test_duplicate_definitions_say_only_that_the_name_exists(self) -> None:
        """Existence is certain, everything else is not -- and absence must not be inferred."""
        facts = extract("""
            try:
                def f(a=1): ...
            except ImportError:
                def f(a=2): ...
            def g(): ...
        """)
        assert {k: v for k, v in facts.items() if k[0] == "py:pkg.mod.f"} == {
            ("py:pkg.mod.f", "exists"): "true",
            ("py:pkg.mod.f", "kind"): "ambiguous",
        }
        assert ("py:pkg.mod.g", "exists") in facts

    def test_an_ambiguous_symbol_is_anchored_at_its_first_definition(self) -> None:
        claims = PythonCodeImporter("o", "r").extract(
            {"src/pkg/mod.py": b"def f(): ...\n\n\ndef f(): ...\n"}, COMMIT
        )
        exists = next(c for c in claims if c.symbol_key == "py:pkg.mod.f" and c.aspect == "exists")
        anchor = anchors.parse(exists.anchor_uri)
        assert (anchor.line_start, anchor.line_end) == (1, 1)

    def test_private_duplicates_stay_hidden(self) -> None:
        facts = extract("def _f(): ...\ndef _f(): ...\n")
        assert not [k for k in facts if k[0] == "py:pkg.mod._f"]

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


def closed(source: str, symbol: str = "py:pkg.mod", **kwargs: bool) -> str | None:
    """The emitted ``namespace_closed`` value for ``symbol`` (None if not emitted)."""
    return extract(source, **kwargs).get((symbol, "namespace_closed"))


class TestModuleClosure:
    def test_plain_module_is_closed(self) -> None:
        assert closed("import os\nX = 1\ndef f(): ...\nclass C: ...") == "true"

    @pytest.mark.parametrize(
        "source",
        [
            "def __getattr__(name): raise AttributeError(name)",
            "from os.path import *",
            "globals()['dyn'] = 1",
            "vars().update(a=1)",
            "locals()['x'] = 1",
            "exec('x = 1')",
            "eval('1')",
            "import sys\nsys.modules[__name__].x = 1",
            "def register():\n    global dyn\n    dyn = 1",
            "if X:\n    from a import *",
        ],
    )
    def test_dynamic_constructs_open_the_module(self, source: str) -> None:
        assert closed(source) == "false"

    def test_dynamic_calls_inside_functions_do_not_run_at_import_time(self) -> None:
        assert closed("def f():\n    return globals()") == "true"

    def test_dynamic_calls_in_class_bodies_run_at_import_time(self) -> None:
        """A class body executes on import, so `globals()` there can rewrite the module."""
        assert closed("class C:\n    globals()['x'] = 1") == "false"

    def test_a_dynamic_class_body_also_opens_the_class(self) -> None:
        source = "class C:\n    x = vars()\n    locals()['y'] = 1"
        assert closed(source, "py:pkg.mod.C") == "false"

    def test_package_init_is_a_module_too(self) -> None:
        assert closed("X = 1", "py:pkg") is None  # path src/pkg/mod.py names pkg.mod
        facts = extract("X = 1", "src/pkg/__init__.py")
        assert facts[("py:pkg", "namespace_closed")] == "true"


class TestClassClosure:
    def test_class_without_bases_is_closed(self) -> None:
        assert closed("class C:\n    x = 1\n    def m(self): ...", "py:pkg.mod.C") == "true"

    def test_explicit_object_base_is_still_closed(self) -> None:
        assert closed("class C(object): ...", "py:pkg.mod.C") == "true"

    @pytest.mark.parametrize(
        "source",
        [
            "from lib import Base\nclass C(Base): ...",
            "import abc\nclass C(abc.ABC): ...",
            "class Base: ...\nclass C(Base): ...",  # in-file base: inherited members unmodelled
            "class C(metaclass=Meta): ...",
            "class C(Base, object): ...",
            "@register\nclass C: ...",
            "import functools\n@functools.total_ordering\nclass C: ...",
            "class C:\n    def __getattr__(self, name): ...",
            "class C:\n    def __getattribute__(self, name): ...",
            "class C:\n    def __init__(self):\n        setattr(self, 'a', 1)",
            "class C:\n    def __init__(self):\n        self.__dict__.update(a=1)",
            "class C:\n    def m(self):\n        vars(self)['a'] = 1",
        ],
    )
    def test_constructs_that_hide_members_open_the_class(self, source: str) -> None:
        assert closed(source, "py:pkg.mod.C") == "false"

    @pytest.mark.parametrize(
        "decorator", ["@final", "@typing.final", "@runtime_checkable", "@deprecated('x')"]
    )
    def test_allow_listed_decorators_do_not_open_a_class(self, decorator: str) -> None:
        assert closed(f"{decorator}\nclass C: ...", "py:pkg.mod.C") == "true"

    def test_a_module_can_be_closed_while_a_class_in_it_is_not(self) -> None:
        source = "from lib import Base\nclass C(Base): ..."
        assert closed(source) == "true"
        assert closed(source, "py:pkg.mod.C") == "false"

    def test_duplicate_class_definitions_have_no_closure_verdict(self) -> None:
        source = "class C: ...\nclass C: ..."
        assert closed(source, "py:pkg.mod.C") is None
        assert kinds(source)["py:pkg.mod.C"] == "ambiguous"

    def test_functions_have_no_namespace_fact(self) -> None:
        assert closed("def f(): ...", "py:pkg.mod.f") is None


class TestBoundNames:
    """A closed namespace must have *every* bound name listed (ADR-0003)."""

    def test_assignments_and_aliases_exist(self) -> None:
        facts = extract("""
            def _impl(): ...
            connect = _impl
            TIMEOUT: int = 5
            a, (b, c) = 1, (2, 3)
        """)
        for name in ("connect", "TIMEOUT", "a", "b", "c"):
            assert facts[(f"py:pkg.mod.{name}", "exists")] == "true"

    def test_imports_exist_under_the_bound_name(self) -> None:
        facts = extract("""
            import os.path
            import numpy as np
            from a.b import c, d as e
        """)
        for name in ("os", "np", "c", "e"):
            assert facts[(f"py:pkg.mod.{name}", "exists")] == "true"
        assert ("py:pkg.mod.d", "exists") not in facts

    def test_other_binding_forms_exist(self) -> None:
        facts = extract("""
            for i in range(3): ...
            with open('f') as fh: ...
            try:
                pass
            except OSError as err:
                pass
            if (n := 5): ...
            match x:
                case [first, *rest]: ...
                case {"k": v, **others}: ...
        """)
        for name in ("i", "fh", "err", "n", "first", "rest", "v", "others"):
            assert facts[(f"py:pkg.mod.{name}", "exists")] == "true", name

    def test_class_attributes_and_instance_attributes_exist(self) -> None:
        facts = extract("""
            class C:
                limit = 5
                def __init__(self, timeout):
                    self.timeout = timeout
                @classmethod
                def build(cls):
                    cls.registry = {}
                @staticmethod
                def util(x):
                    x.nope = 1
        """)
        for name in ("limit", "timeout", "registry"):
            assert facts[(f"py:pkg.mod.C.{name}", "exists")] == "true"
        assert ("py:pkg.mod.C.nope", "exists") not in facts

    def test_comprehension_variables_do_not_leak(self) -> None:
        facts = extract("xs = [i for i in range(3)]\n")
        assert ("py:pkg.mod.i", "exists") not in facts
        assert ("py:pkg.mod.xs", "exists") in facts

    def test_names_bound_only_inside_functions_are_not_module_attributes(self) -> None:
        facts = extract("def f():\n    local = 1\n")
        assert ("py:pkg.mod.local", "exists") not in facts

    def test_private_bound_names_follow_the_privacy_setting(self) -> None:
        assert ("py:pkg.mod._cache", "exists") not in extract("_cache = {}")
        assert ("py:pkg.mod._cache", "exists") in extract("_cache = {}", include_private=True)

    def test_a_def_that_is_also_assigned_claims_only_existence(self) -> None:
        facts = extract("""
            def f(a=1): ...
            f = wrap(f)
        """)
        assert facts[("py:pkg.mod.f", "exists")] == "true"
        assert ("py:pkg.mod.f", "param_names") not in facts
        assert ("py:pkg.mod.f", "deprecated") not in facts

    def test_a_method_that_is_also_assigned_in_the_class_claims_only_existence(self) -> None:
        facts = extract("""
            class C:
                def m(self, a=1): ...
                m = staticmethod(m)
        """)
        assert facts[("py:pkg.mod.C.m", "exists")] == "true"
        assert ("py:pkg.mod.C.m", "param_names") not in facts

    def test_members_of_a_duplicated_class_abstain(self) -> None:
        facts = extract("class C:\n    def m(self): ...\nclass C:\n    x = 1\n")
        assert {k[0] for k in facts if k[0].startswith("py:pkg.mod.C")} == {"py:pkg.mod.C"}


def kinds(source: str, **kwargs: bool) -> dict[str, str]:
    return {sym: v for (sym, aspect), v in extract(source, **kwargs).items() if aspect == "kind"}


class TestKind:
    """`Symbol.kind` needs a machine-readable value for every symbol (ADR-0004)."""

    def test_each_definition_gets_its_kind(self) -> None:
        assert kinds("""
            def f(): ...
            class C:
                def m(self): ...
                x = 1
                def __init__(self):
                    self.y = 2
            z = 3
        """) == {
            "py:pkg.mod": "module",
            "py:pkg.mod.f": "function",
            "py:pkg.mod.C": "class",
            "py:pkg.mod.C.m": "method",
            "py:pkg.mod.C.__init__": "method",
            "py:pkg.mod.C.x": "attribute",
            "py:pkg.mod.C.y": "attribute",
            "py:pkg.mod.z": "attribute",
        }

    def test_a_rebound_definition_is_an_attribute(self) -> None:
        assert kinds("def f(): ...\nf = wrap(f)")["py:pkg.mod.f"] == "attribute"

    def test_every_emitted_symbol_has_exactly_one_kind(self) -> None:
        facts = extract("import os\nclass C:\n    a = 1\ndef f(): ...\n")
        symbols = {sym for sym, _ in facts}
        assert symbols == {sym for sym, aspect in facts if aspect == "kind"}


class TestDecoratedCallables:
    """A decorator can rewrite a signature, so the importer says nothing about it (ADR-0007 §5)."""

    SIGNATURE_ASPECTS = ("param_names", "returns.type")

    def _signature_facts(self, source: str) -> set[str]:
        facts = extract(source)
        return {
            a
            for (_, a) in facts
            if a in self.SIGNATURE_ASPECTS or a.startswith(("param.", "raises."))
        }

    @pytest.mark.parametrize(
        "decorator",
        ["@click.command()", "@app.route('/')", "@my_wrapper", "@functools.wraps(g)", "@retry(3)"],
    )
    def test_an_unknown_decorator_suppresses_all_signature_facts(self, decorator: str) -> None:
        source = f"{decorator}\ndef f(a: int = 1) -> str:\n    raise KeyError\n"
        assert self._signature_facts(source) == set()

    def test_existence_kind_and_deprecation_are_still_stated(self) -> None:
        facts = extract("@click.command()\ndef f(a): ...\n")
        assert facts[("py:pkg.mod.f", "exists")] == "true"
        assert facts[("py:pkg.mod.f", "kind")] == "function"
        assert facts[("py:pkg.mod.f", "deprecated")] == "false"

    @pytest.mark.parametrize(
        "decorator",
        [
            "@staticmethod",
            "@classmethod",
            "@abc.abstractmethod",
            "@property",
            "@typing.final",
            "@deprecated('x')",
            "@functools.lru_cache(maxsize=None)",
            "@cache",
            "@cached_property",
        ],
    )
    def test_decorators_that_preserve_the_signature_do_not_suppress_it(
        self, decorator: str
    ) -> None:
        source = f"class C:\n    {decorator}\n    def f(self, a=1): ...\n"
        assert "param.a.default" in self._signature_facts(source)

    def test_property_accessors_are_safe(self) -> None:
        source = (
            "class C:\n    @property\n    def x(self): ...\n"
            "    @x.setter\n    def x(self, v): ...\n"
        )
        assert extract(source)[("py:pkg.mod.C.x", "exists")] == "true"

    def test_one_unknown_decorator_among_safe_ones_still_suppresses(self) -> None:
        source = "@staticmethod\n@weird\ndef f(a=1): ...\n"
        assert self._signature_facts(source) == set()

    def test_undecorated_functions_are_unaffected(self) -> None:
        assert "param.a.default" in self._signature_facts("def f(a=1): ...\n")
