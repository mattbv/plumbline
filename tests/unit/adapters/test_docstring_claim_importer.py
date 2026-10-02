"""What a docstring claims, and everything it must stay silent about (PRD ING-2, ADR-0006)."""

from __future__ import annotations

from datetime import UTC, datetime
from textwrap import dedent

import pytest

from plumbline.adapters.docstring_claim_importer import PRINCIPAL, DocstringClaimImporter
from plumbline.application.ports import CommitRef, DocExtraction
from plumbline.domain import anchors

SHA = "abcdef0123456789abcdef0123456789abcdef01"
COMMIT = CommitRef(sha=SHA, committed_at=datetime(2024, 1, 1, tzinfo=UTC), changed_paths=())


def extraction(source: str, path: str = "src/pkg/mod.py", **kwargs: bool) -> DocExtraction:
    return DocstringClaimImporter("acme", "sdk", **kwargs).extract(
        {path: dedent(source).encode()}, COMMIT
    )


def claims(source: str, **kwargs: bool) -> dict[tuple[str, str], str]:
    """``{(symbol, aspect): value}`` for one file."""
    return {(c.symbol_key, c.aspect): c.raw_value for c in extraction(source, **kwargs).claims}


F = "py:pkg.mod.f"


class TestGoogleStyle:
    SOURCE = '''
        def f(host, timeout=30):
            """Open a connection.

            Args:
                host (str): Host name.
                timeout (int, optional): Seconds to wait. Defaults to 30.
                *args: Extra positionals.
                **kwargs: Extra keywords.

            Returns:
                bool: True if it opened.

            Raises:
                KeyError: If the host is unknown.
                TimeoutError: If it is too slow.
            """
    '''

    def test_parameters_types_defaults_returns_and_raises(self) -> None:
        facts = claims(self.SOURCE)
        assert facts[(F, "param.host.exists")] == "true"
        assert facts[(F, "param.host.type")] == "str"
        assert facts[(F, "param.timeout.exists")] == "true"
        assert facts[(F, "param.timeout.type")] == "int"
        assert facts[(F, "param.timeout.default")] == "30"
        assert facts[(F, "returns.type")] == "bool"
        assert facts[(F, "raises.KeyError")] == "true"
        assert facts[(F, "raises.TimeoutError")] == "true"

    def test_star_parameters_are_not_named_parameters(self) -> None:
        facts = claims(self.SOURCE)
        assert not [k for k in facts if k[1] in ("param.args.exists", "param.kwargs.exists")]

    def test_it_never_states_a_negative(self) -> None:
        """A docstring that does not mention a parameter says nothing about it."""
        facts = claims('def f(a, b):\n    """Doc.\n\n    Args:\n        a: First.\n    """\n')
        assert (F, "param.a.exists") in facts
        assert (F, "param.b.exists") not in facts
        assert not [v for v in facts.values() if v == "false"]

    @pytest.mark.parametrize(
        ("prose", "expected"),
        [
            ("Seconds. Defaults to 30.", "30"),
            ("Seconds. Default is 30 seconds.", "30"),
            ("Seconds (default: 30).", "30"),
            ("Mode. Defaults to 'fast'.", "'fast'"),
            ('Mode. Defaults to "fast".', "'fast'"),
            ("Flag. Defaults to `True`.", "True"),
            ("Thing. default None", "None"),
            ("Ratio. Defaults to 1.5.", "1.5"),
            ("Offset. Defaults to -1.", "-1"),
        ],
    )
    def test_defaults_are_read_from_prose_and_canonicalized(
        self, prose: str, expected: str
    ) -> None:
        source = f'def f(x):\n    """Doc.\n\n    Args:\n        x: {prose}\n    """\n'
        assert claims(source)[(F, "param.x.default")] == expected

    @pytest.mark.parametrize(
        "prose",
        [
            "Defaults to the value of TIMEOUT.",
            "Defaults to 30s.",
            "Defaults to MY_DEFAULT.",
            "No default here.",
        ],
    )
    def test_a_default_that_is_not_a_plain_literal_is_not_claimed(self, prose: str) -> None:
        source = f'def f(x):\n    """Doc.\n\n    Args:\n        x: {prose}\n    """\n'
        assert (F, "param.x.default") not in claims(source)

    def test_a_default_continued_on_the_next_line_is_found(self) -> None:
        source = '''
            def f(x):
                """Doc.

                Args:
                    x (int): The number
                        of retries. Defaults to 3.
                """
        '''
        assert claims(source)[(F, "param.x.default")] == "3"

    def test_types_are_canonicalized_like_the_code_importers(self) -> None:
        source = '''
            def f(a, b, c):
                """Doc.

                Args:
                    a (Optional[int]): One.
                    b (Union[str, int]): Two.
                    c (typing.List[int]): Three.
                """
        '''
        facts = claims(source)
        assert facts[(F, "param.a.type")] == "None | int"
        assert facts[(F, "param.b.type")] == "int | str"
        assert facts[(F, "param.c.type")] == "List[int]"

    def test_prose_where_a_type_should_be_yields_the_parameter_but_no_type(self) -> None:
        source = '''
            def f(a):
                """Doc.

                Args:
                    a (list of str): The things.
                """
        '''
        facts = claims(source)
        assert facts[(F, "param.a.exists")] == "true"
        assert (F, "param.a.type") not in facts


class TestReturns:
    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("int: The count.", "int"),
            ("dict[str, int]: Mapping.", "dict[str, int]"),
            ("Foo: A foo.", "Foo"),
        ],
    )
    def test_a_typed_return_is_claimed(self, line: str, expected: str) -> None:
        source = f'def f():\n    """Doc.\n\n    Returns:\n        {line}\n    """\n'
        assert claims(source)[(F, "returns.type")] == expected

    @pytest.mark.parametrize(
        "line",
        ["The result of the call.", "result: the result", "Note: see below", "value: the value"],
    )
    def test_a_label_or_sentence_is_not_a_return_type(self, line: str) -> None:
        source = f'def f():\n    """Doc.\n\n    Returns:\n        {line}\n    """\n'
        assert (F, "returns.type") not in claims(source)


class TestNumpyStyle:
    SOURCE = '''
        def f(host, timeout=30):
            """Open a connection.

            Parameters
            ----------
            host : str
                Host name.
            timeout : int, optional
                Seconds to wait. Default is 30.
            x, y : float
                Coordinates.

            Returns
            -------
            bool
                True if it opened.

            Raises
            ------
            KeyError
                If the host is unknown.
            """
    '''

    def test_parameters_returns_and_raises(self) -> None:
        facts = claims(self.SOURCE)
        assert facts[(F, "param.host.type")] == "str"
        assert facts[(F, "param.timeout.type")] == "int"
        assert facts[(F, "param.timeout.default")] == "30"
        assert facts[(F, "returns.type")] == "bool"
        assert facts[(F, "raises.KeyError")] == "true"

    def test_several_names_on_one_line_share_a_type(self) -> None:
        facts = claims(self.SOURCE)
        assert facts[(F, "param.x.type")] == facts[(F, "param.y.type")] == "float"

    def test_a_default_in_the_type_line_is_structured(self) -> None:
        source = '''
            def f(n):
                """Doc.

                Parameters
                ----------
                n : int, default 5
                    Count.
                """
        '''
        out = extraction(source)
        default = next(c for c in out.claims if c.aspect == "param.n.default")
        assert (default.raw_value, default.confidence) == ("5", 0.95)

    def test_several_return_values_are_not_a_single_type(self) -> None:
        source = '''
            def f():
                """Doc.

                Returns
                -------
                a : int
                    One.
                b : str
                    Two.
                """
        '''
        assert (F, "returns.type") not in claims(source)

    def test_a_lone_lowercase_word_is_not_a_return_type(self) -> None:
        source = (
            'def f():\n    """Doc.\n\n    Returns\n    -------\n'
            '    value\n        The value.\n    """\n'
        )
        assert (F, "returns.type") not in claims(source)


class TestSphinxStyle:
    SOURCE = '''
        def f(host, timeout=30):
            """Open a connection.

            :param str host: Host name.
            :param timeout: Seconds to wait. Defaults to 30.
            :type timeout: int
            :returns: whether it opened
            :rtype: bool
            :raises KeyError: if the host is unknown
            """
    '''

    def test_inline_and_separate_types_returns_and_raises(self) -> None:
        facts = claims(self.SOURCE)
        assert facts[(F, "param.host.type")] == "str"
        assert facts[(F, "param.timeout.type")] == "int"
        assert facts[(F, "param.timeout.default")] == "30"
        assert facts[(F, "returns.type")] == "bool"
        assert facts[(F, "raises.KeyError")] == "true"

    def test_a_type_with_spaces_and_brackets(self) -> None:
        source = 'def f(m):\n    """Doc.\n\n    :param dict[str, int] m: A map.\n    """\n'
        assert claims(source)[(F, "param.m.type")] == "dict[str, int]"


class TestDeprecation:
    def test_the_directive_marks_a_function_a_method_and_a_class(self) -> None:
        source = '''
            def f():
                """Old.

                .. deprecated:: 1.2
                   Use g.
                """

            class C:
                """Old class.

                .. deprecated:: 2.0
                """

                def m(self):
                    """Old method.

                    .. deprecated:: 2.0
                    """
        '''
        facts = claims(source)
        assert facts[(F, "deprecated")] == "true"
        assert facts[("py:pkg.mod.C", "deprecated")] == "true"
        assert facts[("py:pkg.mod.C.m", "deprecated")] == "true"

    def test_no_directive_is_no_claim(self) -> None:
        assert not [k for k in claims('def f():\n    """Fine."""\n') if k[1] == "deprecated"]


class TestAbstention:
    def test_a_parameter_listed_twice_with_different_types_keeps_only_what_agrees(self) -> None:
        source = '''
            def f(a):
                """Doc.

                Args:
                    a (int): One.
                    a (str): Two.
                """
        '''
        facts = claims(source)
        assert facts[(F, "param.a.exists")] == "true"  # both listings agree it exists
        assert (F, "param.a.type") not in facts  # they disagree on the type: say nothing

    def test_two_styles_that_disagree_drop_the_disputed_aspect(self) -> None:
        source = '''
            def f(a):
                """Doc.

                Args:
                    a (int): One.

                :param str a: Also one.
                """
        '''
        facts = claims(source)
        assert (F, "param.a.type") not in facts
        assert facts[(F, "param.a.exists")] == "true"  # they agree that it exists

    def test_methods_do_not_claim_self_or_cls(self) -> None:
        source = '''
            class C:
                def m(self, a):
                    """Doc.

                    Args:
                        self: Ignored.
                        a (int): One.
                    """
        '''
        facts = claims(source)
        assert ("py:pkg.mod.C.m", "param.self.exists") not in facts
        assert facts[("py:pkg.mod.C.m", "param.a.type")] == "int"

    def test_a_class_docstring_is_read_only_for_deprecation(self) -> None:
        source = 'class C:\n    """Doc.\n\n    Args:\n        a (int): One.\n    """\n'
        assert claims(source) == {}

    def test_module_docstrings_are_ignored(self) -> None:
        assert claims('"""Module.\n\nArgs:\n    a (int): x.\n"""\n') == {}

    def test_undocumented_symbols_yield_nothing(self) -> None:
        assert claims("def f(a): ...\n") == {}


class TestWhichSymbols:
    SOURCE = '''
        def pub():
            """.. deprecated:: 1"""
        def _priv():
            """.. deprecated:: 1"""
        def dup():
            """.. deprecated:: 1"""
        def dup():
            """.. deprecated:: 1"""
        def rebound():
            """.. deprecated:: 1"""
        rebound = wrap(rebound)
        class Dup:
            def m(self):
                """.. deprecated:: 1"""
        class Dup:
            pass
    '''

    def test_only_symbols_the_code_importer_also_describes(self) -> None:
        symbols = {k[0] for k in claims(self.SOURCE)}
        assert symbols == {"py:pkg.mod.pub"}

    def test_private_symbols_follow_the_privacy_setting(self) -> None:
        assert "py:pkg.mod._priv" in {k[0] for k in claims(self.SOURCE, include_private=True)}


class TestFiles:
    def test_a_file_that_does_not_parse_is_not_analyzed(self) -> None:
        out = DocstringClaimImporter("o", "r").extract(
            {
                "src/pkg/ok.py": b'def f():\n    """.. deprecated:: 1"""\n',
                "src/pkg/bad.py": b"def (:\n",
            },
            COMMIT,
        )
        assert out.analyzed_paths == {"src/pkg/ok.py"}

    def test_a_file_without_docstrings_is_still_analyzed(self) -> None:
        """So that deleting the last docstring retracts its claims."""
        assert extraction("def f(): ...\n").analyzed_paths == {"src/pkg/mod.py"}

    def test_non_python_files_are_not_analyzed(self) -> None:
        out = DocstringClaimImporter("o", "r").extract({"README.md": b"# hi"}, COMMIT)
        assert out == DocExtraction([], frozenset())

    def test_handles_python_files_only(self) -> None:
        importer = DocstringClaimImporter("o", "r")
        assert importer.handles("a/b.py") and not importer.handles("README.md")


class TestClaimShape:
    SOURCE = 'def f(a):\n    """Doc.\n\n    Args:\n        a (int): One. Defaults to 3.\n    """\n'

    def test_the_author_is_the_docstring_principal(self) -> None:
        assert DocstringClaimImporter("o", "r").principal == PRINCIPAL == "plumb-docstring"

    def test_the_anchor_is_the_symbol_at_the_commit(self) -> None:
        claim = extraction(self.SOURCE).claims[0]
        anchor = anchors.parse(claim.anchor_uri)
        assert (anchor.owner, anchor.repo, anchor.commit_sha) == ("acme", "sdk", SHA)
        assert (anchor.path, anchor.symbol) == ("src/pkg/mod.py", "pkg.mod.f")

    def test_confidence_reflects_how_structured_the_source_is(self) -> None:
        by_aspect = {c.aspect: c for c in extraction(self.SOURCE).claims}
        assert by_aspect["param.a.type"].confidence == 0.95
        assert by_aspect["param.a.default"].confidence == 0.7

    def test_the_rationale_names_the_rule_and_the_importer_version(self) -> None:
        claim = next(c for c in extraction(self.SOURCE).claims if c.aspect == "param.a.type")
        assert "docstring.google:Args 'a'" in claim.rationale
        assert "[docstring-claim-importer/1]" in claim.rationale

    def test_output_is_sorted_and_independent_of_input_order(self) -> None:
        importer = DocstringClaimImporter("o", "r")
        a = b'def f(x):\n    """.. deprecated:: 1"""\n'
        b = b'def g(y):\n    """.. deprecated:: 1"""\n'
        one = importer.extract({"src/pkg/a.py": a, "src/pkg/b.py": b}, COMMIT)
        two = importer.extract({"src/pkg/b.py": b, "src/pkg/a.py": a}, COMMIT)
        assert one == two
        keys = [(c.symbol_key, c.aspect, c.raw_value) for c in one.claims]
        assert keys == sorted(keys)

    def test_the_fact_key_joins_symbol_and_aspect(self) -> None:
        claim = extraction(self.SOURCE).claims[0]
        assert claim.fact_key == f"{claim.symbol_key}#{claim.aspect}"
