"""Tests for tools.interp.compile."""

from __future__ import annotations

import pytest

from tools.interp.compile import PartError, compile_part, part_key, part_to_regex
from tools.model import Part
from tools.model.java_regex import JavaRegexError


def matches(part: Part, text: str) -> bool:
    return compile_part(part).fullmatch(text) is not None


def test_part_to_regex_forms() -> None:
    assert part_to_regex({"seq": [{"regex": "a"}, {"regex": "b"}]}) == "(?:(?:a)(?:b))"
    assert part_to_regex({"alt": [{"regex": "a"}, {"regex": "b"}]}) == "(?:(?:a)|(?:b))"
    assert part_to_regex({"opt": {"regex": "a"}}) == "(?:(?:a))?"
    assert part_to_regex({"star": {"regex": "a"}}) == "(?:(?:a))*"
    assert part_to_regex({"plus": {"regex": "a"}}) == "(?:(?:a))+"
    assert part_to_regex({"literal": "a.b", "ci": True}) == "(?:[aA]\\.[bB])"
    assert part_to_regex({"literal": "a", "ci": False}) == "(?:a)"
    assert part_to_regex({"regex": "a.", "ci": True}) == "(?:[aA][^\\n\\r\\x85\\u2028\\u2029])"


def test_regexes_have_java_semantics_not_python_unicode() -> None:
    assert matches({"regex": "\\d\\w\\s"}, "1a ")
    assert not matches({"regex": "\\d"}, "\u0663")
    assert not matches({"regex": "\\w"}, "\xe9")
    assert not matches({"regex": "\\s"}, "\xa0")
    assert matches({"regex": "[\\s\xa0]"}, "\xa0")
    assert not matches({"regex": "a.b"}, "a\u2028b")
    assert matches({"regex": "\\p{L}\\p{N}"}, "\xe9\u0663")
    assert not matches({"regex": "k", "ci": True}, "\u212a")
    assert not matches({"literal": "\xe9", "ci": True}, "\xc9")
    assert matches({"literal": "k", "ci": True}, "K")


def test_implicit_dollar_accepts_one_final_line_terminator() -> None:
    assert matches({"regex": "title(.*)"}, "title a\u2028")
    assert matches({"regex": "title(.*)"}, "title a\x85")
    assert not matches({"regex": "title(.*)"}, "title a\u2028b")
    assert not matches({"regex": "title(.*)"}, "title a\u2028\u2028")
    assert matches({"regex": "a$"}, "a\u2029")


def test_unsupported_java_syntax_raises_java_regex_error() -> None:
    with pytest.raises(JavaRegexError):
        part_to_regex({"regex": "[a[b]]"})


def test_literal_ci_flag_controls_case_sensitivity() -> None:
    assert matches({"literal": "Class", "ci": True}, "cLASS")
    assert not matches({"literal": "Class", "ci": False}, "class")
    assert matches({"literal": "Class", "ci": False}, "Class")


def test_literal_is_escaped() -> None:
    assert matches({"literal": "a.b", "ci": True}, "a.b")
    assert not matches({"literal": "a.b", "ci": True}, "axb")


def test_regex_leaf_is_case_insensitive_only_with_ci_true() -> None:
    assert matches({"regex": "abc", "ci": True}, "ABC")
    assert not matches({"regex": "abc"}, "ABC")
    assert not matches({"regex": "abc", "ci": False}, "ABC")
    assert matches({"regex": "abc"}, "abc")


def test_unicode_property_classes_need_regex_module() -> None:
    assert matches({"plus": {"regex": "[\\p{L}\\p{N}_]"}}, "héllo1")


def test_match_is_whole_line_not_prefix() -> None:
    assert not matches({"regex": "ab"}, "abc")
    assert not matches({"regex": "bc"}, "abc")


def test_quantifiers_and_alternation() -> None:
    part: Part = {"seq": [{"alt": [{"regex": "x"}, {"regex": "y"}]}, {"star": {"regex": "z"}}]}
    assert matches(part, "yzzz")
    assert matches(part, "x")
    assert not matches(part, "xy")


def test_compile_is_memoized_per_distinct_part() -> None:
    a = compile_part({"regex": "memo\\d"})
    b = compile_part({"regex": "memo\\d"})
    assert a is b
    assert part_key({"b": 1, "a": 2}) == part_key({"a": 2, "b": 1})


@pytest.mark.parametrize("bad", [{"ref": "X"}, {}])
def test_unresolved_part_raises(bad: Part) -> None:
    with pytest.raises(PartError):
        part_to_regex(bad)
