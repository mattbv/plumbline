"""The source edits behind the seeded-drift measurement must touch exactly one thing."""

from __future__ import annotations

import ast
import difflib
from textwrap import dedent

import pytest
from evaluation import mutations as m

SOURCE = dedent('''
    def connect(host: str, timeout: int = 30, *, retries: int = 3, mode="fast") -> bool:
        """Open a connection.

        Args:
            host (str): Host name.
            timeout (int, optional): Seconds to wait. Defaults to 30.
            retries (int): How often. Default is 3.

        Returns:
            bool: True if it opened.

        Raises:
            KeyError: If the host is unknown.
        """
        if not host:
            raise KeyError(host)
        return True


    class Client:
        def close(self, force=False):
            """Close it."""
            return force

        def other(self) -> None:
            return None
''')


def changed_lines(before: str, after: str) -> list[str]:
    return [
        d
        for d in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
        if d[0] in "+-" and d[:3] not in ("+++", "---")
    ]


class TestFindFunction:
    def test_a_function_and_a_method(self) -> None:
        tree = ast.parse(SOURCE)
        assert m.find_function(tree, "connect") is not None
        assert m.find_function(tree, "Client.close") is not None

    def test_missing_or_ambiguous_names_are_none(self) -> None:
        assert m.find_function(ast.parse(SOURCE), "nope") is None
        assert m.find_function(ast.parse("def f(): ...\ndef f(): ..."), "f") is None

    def test_functions_inside_conditionals_are_found(self) -> None:
        assert m.find_function(ast.parse("if X:\n    def f(): ..."), "f") is not None


class TestSignatureEdits:
    def test_a_positional_default(self) -> None:
        out = m.set_default(SOURCE, "connect", "timeout", "37")
        assert changed_lines(SOURCE, out or "") == [
            '-def connect(host: str, timeout: int = 30, *, retries: int = 3, mode="fast") -> bool:',
            '+def connect(host: str, timeout: int = 37, *, retries: int = 3, mode="fast") -> bool:',
        ]

    def test_a_keyword_only_default(self) -> None:
        out = m.set_default(SOURCE, "connect", "retries", "9")
        assert out is not None and "retries: int = 9" in out and "timeout: int = 30" in out

    def test_a_default_without_an_annotation(self) -> None:
        out = m.set_default(SOURCE, "connect", "mode", "'slow'")
        assert out is not None and "mode='slow'" in out

    def test_a_parameter_with_no_default_cannot_be_given_one(self) -> None:
        assert m.set_default(SOURCE, "connect", "host", "1") is None

    def test_an_unknown_parameter_or_function_is_none(self) -> None:
        assert m.set_default(SOURCE, "connect", "zzz", "1") is None
        assert m.set_default(SOURCE, "nope", "x", "1") is None

    def test_a_parameter_annotation(self) -> None:
        out = m.set_param_annotation(SOURCE, "connect", "timeout", "float")
        assert out is not None and "timeout: float = 30" in out and "host: str" in out

    def test_a_parameter_with_no_annotation_has_nothing_to_replace(self) -> None:
        assert m.set_param_annotation(SOURCE, "connect", "mode", "int") is None

    def test_the_return_annotation(self) -> None:
        out = m.set_return_annotation(SOURCE, "connect", "str")
        assert out is not None and ") -> str:" in out

    def test_no_return_annotation_means_nothing_to_replace(self) -> None:
        assert m.set_return_annotation(SOURCE, "Client.close", "int") is None

    def test_renaming_a_parameter_changes_only_the_signature(self) -> None:
        out = m.rename_param(SOURCE, "connect", "timeout", "timeout_s")
        assert out is not None
        assert len(changed_lines(SOURCE, out)) == 2
        assert "timeout_s: int = 30" in out
        assert "timeout (int, optional)" in out  # the docstring still documents the old name

    def test_renaming_a_method_parameter(self) -> None:
        out = m.rename_param(SOURCE, "Client.close", "force", "hard")
        assert out is not None and "def close(self, hard=False)" in out

    def test_non_ascii_text_before_the_target_does_not_shift_the_edit(self) -> None:
        source = 'def f(naïve: str = "é", x: int = 1):\n    return x\n'
        out = m.set_default(source, "f", "x", "2")
        assert out == 'def f(naïve: str = "é", x: int = 2):\n    return x\n'

    def test_windows_line_endings_are_preserved(self) -> None:
        source = 'def f(a: int = 1) -> int:\r\n    """Doc."""\r\n    return a\r\n'
        out = m.set_default(source, "f", "a", "9")
        assert out == 'def f(a: int = 9) -> int:\r\n    """Doc."""\r\n    return a\r\n'

    def test_a_multi_line_signature(self) -> None:
        source = "def f(\n    a: int,\n    b: int = 5,\n) -> None:\n    return None\n"
        out = m.set_default(source, "f", "b", "6")
        assert out == "def f(\n    a: int,\n    b: int = 6,\n) -> None:\n    return None\n"

    def test_every_edit_keeps_the_file_parseable(self) -> None:
        for out in (
            m.set_default(SOURCE, "connect", "timeout", "37"),
            m.set_param_annotation(SOURCE, "connect", "host", "bytes"),
            m.set_return_annotation(SOURCE, "connect", "int"),
            m.rename_param(SOURCE, "connect", "host", "hostname"),
        ):
            assert out is not None
            ast.parse(out)

    def test_an_edit_that_changes_nothing_is_none(self) -> None:
        assert m.set_default(SOURCE, "connect", "timeout", "30") is None

    def test_an_edit_that_breaks_the_syntax_is_none(self) -> None:
        assert m.set_default(SOURCE, "connect", "timeout", "(") is None


class TestBodyEdits:
    def test_a_statement_goes_after_the_docstring_at_the_body_indent(self) -> None:
        out = m.insert_after_docstring(SOURCE, "connect", "_seeded = 0")
        assert out is not None
        lines = out.splitlines()
        at = next(i for i, ln in enumerate(lines) if "_seeded" in ln)
        assert lines[at] == "    _seeded = 0" and lines[at - 1].strip() == '"""'

    def test_in_a_method_the_indent_is_the_methods(self) -> None:
        out = m.insert_after_docstring(SOURCE, "Client.other", "# note")
        assert out is not None and "        # note\n        return None" in out

    def test_a_function_with_no_docstring(self) -> None:
        source = "def f():\n    return 1\n"
        assert (
            m.insert_after_docstring(source, "f", "x = 1") == "def f():\n    x = 1\n    return 1\n"
        )

    def test_a_one_line_function_is_left_alone(self) -> None:
        assert m.insert_after_docstring("def f(): return 1\n", "f", "x = 1") is None

    def test_the_documented_raise_is_replaced(self) -> None:
        out = m.replace_raise_with_pass(SOURCE, "connect", "KeyError")
        assert out is not None and "raise KeyError" not in out and "        pass\n" in out

    def test_a_raise_of_something_else_is_not_touched(self) -> None:
        assert m.replace_raise_with_pass(SOURCE, "connect", "ValueError") is None

    def test_a_raise_inside_a_nested_function_is_not_this_functions(self) -> None:
        source = "def f():\n    def g():\n        raise KeyError\n    return g\n"
        assert m.replace_raise_with_pass(source, "f", "KeyError") is None

    def test_a_dotted_exception_matches_by_its_last_name(self) -> None:
        source = "def f():\n    raise json.JSONDecodeError('x', '', 0)\n"
        assert m.replace_raise_with_pass(source, "f", "JSONDecodeError") == "def f():\n    pass\n"

    def test_append_a_function(self) -> None:
        out = m.append_function(SOURCE, "seeded_extra")
        assert out is not None and out.endswith("def seeded_extra():\n    return None\n")


class TestDocstringSite:
    def test_it_finds_a_plain_docstring_and_its_indent(self) -> None:
        site = m.docstring_site(SOURCE, "Client.close")
        assert site is not None and site.value == "Close it." and site.indent == "        "

    @pytest.mark.parametrize(
        "source",
        [
            "def f():\n    '''single quoted'''\n",
            'def f():\n    r"""raw"""\n',
            'def f():\n    """has a \\n escape"""\n',
            "def f():\n    return 1\n",
        ],
    )
    def test_unusual_or_missing_docstrings_are_not_edited(self, source: str) -> None:
        assert m.docstring_site(source, "f") is None

    def test_replacing_a_docstring_sets_exactly_the_new_value(self) -> None:
        out = m.replace_docstring(SOURCE, "Client.close", "Close it.\n\n        Gently.\n        ")
        assert out is not None
        node = m.find_function(ast.parse(out), "Client.close")
        assert (
            node is not None
            and ast.get_docstring(node, clean=False) == "Close it.\n\n        Gently.\n        "
        )

    def test_a_value_that_cannot_be_written_safely_is_refused(self) -> None:
        assert m.replace_docstring(SOURCE, "Client.close", 'has """ inside') is None
        assert m.replace_docstring(SOURCE, "Client.close", "has \\ backslash") is None


class TestDocstringValueEdits:
    VALUE = m.docstring_site(SOURCE, "connect").value  # type: ignore[union-attr]

    def test_the_stated_default_of_one_parameter(self) -> None:
        out = m.docstring_set_default(self.VALUE, "timeout", "99")
        assert out is not None and "Defaults to 99." in out and "Default is 3." in out

    def test_another_parameter_is_not_confused(self) -> None:
        out = m.docstring_set_default(self.VALUE, "retries", "8")
        assert out is not None and "Default is 8." in out and "Defaults to 30." in out

    def test_the_stated_default_is_the_literal_not_the_word_default_in_prose(self) -> None:
        value = (
            "Doc.\n\nArgs:\n    theme (T, optional): Or None to use default. Defaults to None.\n"
        )
        out = m.docstring_set_default(value, "theme", "0")
        assert (
            out
            == "Doc.\n\nArgs:\n    theme (T, optional): Or None to use default. Defaults to 0.\n"
        )

    def test_with_two_literals_the_last_is_the_stated_default(self) -> None:
        value = "Doc.\n\nArgs:\n    n (int): Default 1 in tests. Defaults to 3.\n"
        out = m.docstring_set_default(value, "n", "9")
        assert out == "Doc.\n\nArgs:\n    n (int): Default 1 in tests. Defaults to 9.\n"

    def test_prose_after_the_default_is_not_mistaken_for_it(self) -> None:
        value = "Doc.\n\nArgs:\n    n (int): Defaults to 5; see the default behaviour.\n"
        out = m.docstring_set_default(value, "n", "9")
        assert out == "Doc.\n\nArgs:\n    n (int): Defaults to 9; see the default behaviour.\n"

    def test_a_default_in_a_continuation_line_is_found(self) -> None:
        value = "Doc.\n\nArgs:\n    n (int): How many,\n        in total. Defaults to 3.\n"
        out = m.docstring_set_default(value, "n", "9")
        assert out is not None and "Defaults to 9." in out

    def test_a_parameter_with_no_stated_default_is_none(self) -> None:
        assert m.docstring_set_default(self.VALUE, "host", "1") is None
        assert m.docstring_set_default(self.VALUE, "zzz", "1") is None

    def test_a_quoted_default(self) -> None:
        value = "Doc.\n\nArgs:\n    mode (str): The mode. Defaults to 'fast'.\n"
        assert m.docstring_set_default(value, "mode", "'slow'") == value.replace("'fast'", "'slow'")

    def test_a_parameter_type_keeps_its_qualifiers(self) -> None:
        out = m.docstring_set_param_type(self.VALUE, "timeout", "float")
        assert out is not None and "timeout (float, optional):" in out and "host (str):" in out

    def test_a_missing_parameter_type_is_none(self) -> None:
        assert m.docstring_set_param_type("Doc.\n\nArgs:\n    x: untyped.\n", "x", "int") is None

    def test_the_return_type(self) -> None:
        out = m.docstring_set_return_type(self.VALUE, "str")
        assert out is not None and "str: True if it opened." in out

    def test_no_returns_section_is_none(self) -> None:
        assert m.docstring_set_return_type("Doc.\n\nArgs:\n    x (int): y.\n", "str") is None

    def test_an_invented_parameter_goes_at_the_end_of_args(self) -> None:
        out = m.docstring_add_param(self.VALUE, "ghost", "int")
        assert out is not None
        lines = out.split("\n")
        at = next(i for i, ln in enumerate(lines) if "ghost (int)" in ln)
        assert lines[at - 1].strip().startswith("retries") or "Default is 3" in lines[at - 1]
        assert lines[at + 1].strip() == "" and lines[at + 2].strip() == "Returns:"

    def test_a_docstring_without_args_cannot_take_one(self) -> None:
        assert m.docstring_add_param("Just prose.", "ghost", "int") is None

    def test_a_deprecation_directive_is_appended(self) -> None:
        out = m.docstring_add_deprecated("Close it.", "        ")
        assert ".. deprecated:: 9.9" in out and out.startswith("Close it.")

    def test_rewording_the_summary_leaves_the_structure_alone(self) -> None:
        out = m.docstring_edit_summary(self.VALUE)
        assert out is not None and out.startswith("Open a connection. (reworded)\n")
        assert out.split("\n")[1:] == self.VALUE.split("\n")[1:]

    def test_an_empty_summary_cannot_be_reworded(self) -> None:
        assert m.docstring_edit_summary("") is None
