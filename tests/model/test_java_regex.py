"""Tests for tools.model.java_regex: rewrites, Java reference vectors, model coverage."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import regex

from tests.helpers.models import repo_resolved
from tests.model import jre_vectors as vectors
from tools.model import ResolvedModel
from tools.model.java_regex import (
    DOT,
    JavaRegexError,
    line_pattern,
    literal_to_python,
    to_python,
)
from tools.model.java_regex_sets import (
    class_text,
    complement,
    cp_text,
    fold_ascii,
    merge,
    ranges_text,
)

MODEL_DIR = Path(__file__).resolve().parents[2] / "model"
NON_ASCII = {
    "arabic_digit": "٣",
    "e_acute": "\xe9",
    "E_acute": "\xc9",
    "kelvin": "K",
    "long_s": "ſ",
    "dotless_i": "ı",
    "nbsp": "\xa0",
    "nel": "\x85",
    "line_sep": " ",
    "em_space": " ",
}


def accepts(pattern: str, text: str, *, ci: bool = False) -> bool:
    return regex.fullmatch(to_python(pattern, ci=ci), text) is not None


@pytest.mark.parametrize("char", ["\n", "\r", "\x85", " ", " "])
def test_dot_refuses_every_java_line_terminator(char: str) -> None:
    assert not accepts(".", char)


@pytest.mark.parametrize("char", ["\x0b", "\x0c", "\x00", "\xe9", "\U0001f600", " "])
def test_dot_accepts_the_rest(char: str) -> None:
    assert accepts(".", char)


def test_dot_text_is_the_documented_class() -> None:
    assert to_python("a.b") == f"a{DOT}b"
    assert DOT == "[^\\n\\r\\x85\\u2028\\u2029]"


def test_digit_word_space_are_ascii() -> None:
    assert accepts(r"\d", "7") and not accepts(r"\d", NON_ASCII["arabic_digit"])
    assert accepts(r"\w", "_") and not accepts(r"\w", NON_ASCII["e_acute"])
    assert accepts(r"\s", "\x0b") and accepts(r"\s", "\f")
    assert not accepts(r"\s", NON_ASCII["nbsp"]) and not accepts(r"\s", NON_ASCII["nel"])
    assert not accepts(r"\s", NON_ASCII["em_space"])


def test_negated_escapes_take_everything_else() -> None:
    assert accepts(r"\D", NON_ASCII["arabic_digit"]) and not accepts(r"\D", "5")
    assert accepts(r"\W", NON_ASCII["e_acute"]) and not accepts(r"\W", "a")
    assert accepts(r"\S", NON_ASCII["nbsp"]) and not accepts(r"\S", " ")


def test_escapes_inside_classes_keep_ascii_meaning() -> None:
    assert accepts(r"[\w-]", "-") and not accepts(r"[\w-]", NON_ASCII["e_acute"])
    assert accepts(r"[^\w]", NON_ASCII["e_acute"]) and not accepts(r"[^\w]", "z")
    assert accepts(r"[\W]", NON_ASCII["e_acute"]) and not accepts(r"[\W]", "0")
    assert accepts(r"[\s\xa0]", NON_ASCII["nbsp"]) and accepts(r"[\s\xa0]", "\t")
    assert accepts(r"[\D&]", "&") and not accepts(r"[\D]", "0")


def test_posix_classes_are_ascii_but_unicode_properties_are_not() -> None:
    assert accepts(r"\p{Alpha}", "q") and not accepts(r"\p{Alpha}", NON_ASCII["e_acute"])
    assert accepts(r"\p{Punct}", "!") and not accepts(r"\p{Punct}", "\xa1")
    assert accepts(r"\P{Alpha}", NON_ASCII["e_acute"]) and not accepts(r"\P{Alpha}", "q")
    assert accepts(r"\p{L}", NON_ASCII["e_acute"]) and accepts(r"\pL", "α")
    assert accepts(r"\p{Nd}", NON_ASCII["arabic_digit"])
    assert accepts(r"[\p{Alnum}_]", "_") and not accepts(r"[\p{Alnum}]", "٣")


def test_word_boundary_is_ascii_with_the_mark_quirk() -> None:
    assert regex.search(to_python(r"a\bb"), "a b") is None
    assert regex.search(to_python(r"a\b"), "a\xe9") is not None  # e-acute is not a word char
    assert regex.search(to_python(r"a\b"), "á") is None  # a mark continues the word
    assert regex.search(to_python(r"a\B"), "á") is not None
    assert regex.search(to_python(r"\bab"), "-ab") is not None


def test_case_insensitivity_folds_ascii_only() -> None:
    assert accepts("class", "ClAsS", ci=True)
    assert not accepts("class", "ClAsS")
    assert not accepts("k", NON_ASCII["kelvin"], ci=True)
    assert not accepts("s", NON_ASCII["long_s"], ci=True)
    assert not accepts("i", NON_ASCII["dotless_i"], ci=True)
    assert not accepts("\xe9", NON_ASCII["E_acute"], ci=True)
    assert accepts("\xe9", "\xe9", ci=True)


def test_case_insensitive_classes_and_ranges_fold_ascii_only() -> None:
    assert accepts("[a-c]", "B", ci=True) and not accepts("[a-c]", "B")
    assert not accepts("[a-z]", NON_ASCII["kelvin"], ci=True)
    assert not accepts("[^a]", "A", ci=True) and accepts("[^a]", "b", ci=True)
    assert accepts("[Z-a]", "z", ci=True) and not accepts("[Z-a]", "b", ci=True)
    assert accepts(r"\x41", "a", ci=True) and not accepts(r"\x41", "a")
    assert accepts(r"[\x41]", "a", ci=True)


def test_case_insensitive_properties() -> None:
    assert accepts(r"\p{Lu}", "a", ci=True) and not accepts(r"\p{Lu}", "a")
    assert accepts(r"\p{Ll}", "\xc9", ci=True)
    assert not accepts(r"\P{Lu}", "a", ci=True)
    assert accepts(r"\p{Upper}", "a", ci=True) and not accepts(r"\p{Upper}", "\xc9", ci=True)
    assert not accepts(r"\P{Upper}", "a", ci=True) and accepts(r"[\P{Upper}]", "1", ci=True)
    assert accepts(r"[\p{Lu}]", "\xe9", ci=True)


def test_inline_flag_groups_switch_case_mode_locally() -> None:
    assert accepts("a(?i:b)c", "aBc") and not accepts("a(?i:b)c", "aBC")
    assert accepts("(?-i:a)b", "aB", ci=True) and not accepts("(?-i:a)b", "AB", ci=True)
    assert accepts("(?i)ab", "AB") and accepts("(a(?i)b)c", "aBc")
    assert not accepts("(a(?i)b)c", "aBC")
    assert to_python("(?i:a)") == "(?:[aA])"


def test_back_references_under_ci() -> None:
    assert accepts(r"(a)\1", "aA", ci=True) and not accepts(r"(a)\1", "aA")
    assert accepts(r"(?P<x>a)(?P=x)", "aA", ci=True)
    assert accepts(r"(?<x>a)\k<x>", "aA", ci=True) and accepts(r"(?<x>a)\k<x>", "aa")


def test_dollar_and_z_accept_one_final_terminator() -> None:
    assert accepts("a$", "a") and not accepts("a$", "a ")  # fullmatch still needs all text
    assert regex.search(to_python("^a$"), "a ") is not None
    assert regex.search(to_python("^a$"), "a\r\n") is not None
    assert regex.search(to_python("^a$"), "a\n\n") is None
    assert regex.search(to_python("^a\\Z"), "a\x85") is not None
    assert regex.search(to_python("^a\\z"), "a\x85") is None
    assert regex.search(to_python("a$.", ci=True), "a b") is None


def test_line_pattern_adds_the_implicit_dollar() -> None:
    compiled = regex.compile(line_pattern(to_python("title(.*)")))
    assert compiled.fullmatch("title a ") is not None
    assert compiled.fullmatch("title a b") is None
    assert compiled.fullmatch("title a\r\n") is not None
    assert compiled.fullmatch("title a\n\n") is None


def test_literal_to_python() -> None:
    assert literal_to_python("a.b", ci=True) == "[aA]\\.[bB]"
    assert literal_to_python("a.b") == "a\\.b"
    assert regex.fullmatch(literal_to_python("\xe9X", ci=True), "\xe9x")
    assert not regex.fullmatch(literal_to_python("\xe9", ci=True), "\xc9")


def test_pcre_style_constructs_pass_through() -> None:
    source = "(?(DEFINE)(?<r>a))(?&r)(?P<n>b)(?P=n)(?#c)(?=(c))(?(1)d|e)"
    assert to_python(source) == source
    assert accepts("(?(DEFINE)(?<r>a))(?&r)+", "aaa")
    assert accepts("(a)?(?(1)b|c)", "ab") and accepts("(a)?(?(1)b|c)", "c")


def test_possessive_lazy_and_lookarounds_pass_through() -> None:
    assert accepts("a*+b", "aab") and not accepts("a*+a", "aa")
    assert accepts("a+?", "aa")
    assert accepts("(?<=a)b|a", "a") and regex.search(to_python("(?<!a)b"), "ab") is None


@pytest.mark.parametrize(
    "pattern",
    ["[a[b]]", "[a&&b]", "\\h", "\\R", "\\Qa\\E", "(?s)a", "(?x:a)", "a\\", "[a", "[]", "[b-a]"],
)
def test_unsupported_syntax_raises(pattern: str) -> None:
    with pytest.raises(JavaRegexError):
        to_python(pattern)


@pytest.mark.parametrize("pattern", ["[a\\", "\\p", "\\p{"])
def test_malformed_escapes_raise(pattern: str) -> None:
    with pytest.raises(JavaRegexError):
        to_python(pattern)


def test_octal_escape_in_a_class_passes_through() -> None:
    assert to_python("[\\0]") == "[\\0]"


@pytest.mark.parametrize("pattern", ["\\y", "[\\y]", "\\cA", "\\x{41}", "\\k", "(?<", "(?"])
def test_unknown_escapes_and_groups_raise(pattern: str) -> None:
    with pytest.raises(JavaRegexError):
        to_python(pattern)


def test_class_edge_shapes() -> None:
    assert accepts("[-a]", "-") and accepts("[a-]", "-") and accepts("[a\\-z]", "-")
    assert not accepts("[a\\-z]", "m")
    assert accepts("[a-c-e]", "-") and accepts("[\\d-z]", "-")
    assert accepts("[\\t\\n]", "\n") and accepts("[\\u0041]", "A")
    assert accepts("[\\x41-\\x43]", "B") and accepts("[\\.\\]]", "]")
    assert accepts("[a-c\\d]", "5") and accepts("[^\\d\\s]", "x")


def test_sets_helpers() -> None:
    assert merge([(5, 6), (1, 2), (3, 4), (10, 12)]) == [(1, 6), (10, 12)]
    assert complement([(0, 0x10FFFF)]) == []
    assert complement([(0x41, 0x5A)]) == [(0, 0x40), (0x5B, 0x10FFFF)]
    assert complement([(0, 9), (11, 0x10FFFF)]) == [(10, 10)]
    assert complement([(5, 6), (1, 2)]) == [(0, 0), (3, 4), (7, 0x10FFFF)]
    assert fold_ascii([(0x41, 0x43), (0x78, 0x7A)]) == [
        (0x41, 0x43),
        (0x58, 0x5A),
        (0x61, 0x63),
        (0x78, 0x7A),
    ]
    assert fold_ascii([(0x30, 0x39)]) == [(0x30, 0x39)]
    assert fold_ascii([(0x61, 0x62)]) == [(0x41, 0x42), (0x61, 0x62)]
    assert cp_text(0x41) == "A" and cp_text(0x5F) == "\\_"
    assert cp_text(0x2028) == "\\u2028" and cp_text(0x1F600) == "\\U0001f600"
    assert ranges_text([(1, 1), (3, 4), (6, 9)]) == "\\x01\\x03\\x04\\x06-\\x09"
    assert class_text([(0x61, 0x61)], ["\\p{L}"], negated=True) == "[^a\\p{L}]"


def test_vectors_match_java_reference() -> None:
    cases, strings, java = vectors.load()
    assert len(cases) > 1000 and len(strings) > 200
    mismatches = []
    for case, expected in zip(cases, java, strict=True):
        got = vectors.python_verdicts(case, strings)
        wrong = [
            i
            for i, (a, b) in enumerate(zip(got, expected, strict=True))
            if a != b and vectors.comparable(case, strings[i])
        ]
        if wrong:
            mismatches.append((case, [strings[i] for i in wrong[:3]]))
    assert mismatches == []


def test_vectors_exercise_the_divergences() -> None:
    """The naive reading (Python Unicode semantics) must disagree with Java a lot."""
    cases, strings, java = vectors.load()
    different = 0
    for case, expected in zip(cases, java, strict=True):
        source = f"(?i:{case.pattern})" if case.ci else case.pattern
        got = "".join("1" if regex.fullmatch(source, s) else "0" for s in strings)
        different += got != expected
    assert different > 400
    assert sum(v.count("1") for v in java) > 15000


def test_vector_generation_is_deterministic() -> None:
    assert vectors.build_cases(seed=7, count=50) == vectors.build_cases(seed=7, count=50)
    assert vectors.build_cases(seed=7, count=50) != vectors.build_cases(seed=8, count=50)
    assert vectors.build_strings() == vectors.build_strings()
    text = vectors.java_input([vectors.Case("a", True, "line")], ["", "b"])
    assert text == "line\ti\t61\t-,62\n"


def test_every_model_regex_translates_and_compiles() -> None:
    resolved = repo_resolved()
    count = 0
    for model in resolved.values():
        for part in _leaves(model):
            if "regex" in part:
                regex.compile(to_python(part["regex"], ci=bool(part.get("ci"))))
                count += 1
    assert count > 500


def _leaves(model: ResolvedModel) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if "regex" in node:
                found.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(model.contexts)
    walk(model.variables)
    return found


@pytest.mark.corpus
def test_regenerated_vectors_equal_the_committed_fixture() -> None:
    assert shutil.which("java"), "Java 21 is required to regenerate the vectors"
    cases, strings = vectors.build_cases(), vectors.build_strings()
    fresh = vectors.dump(cases, strings, vectors.java_verdicts(cases, strings))
    assert fresh == vectors.VECTORS.read_text(encoding="utf-8")


@pytest.mark.corpus
def test_fresh_seed_agrees_with_live_java() -> None:
    cases, strings = vectors.build_cases(seed=99, count=300), vectors.build_strings(seed=99)
    java = vectors.java_verdicts(cases, strings)
    for case, expected in zip(cases, java, strict=True):
        if expected == vectors.JAVA_ERROR:
            continue
        got = vectors.python_verdicts(case, strings)
        for i, (a, b) in enumerate(zip(got, expected, strict=True)):
            assert a == b or not vectors.comparable(case, strings[i]), (case, strings[i])


def test_end_anchor_replaces_dollar_and_z_but_not_absolute_end() -> None:
    marker = "(?=END)"
    assert to_python("a$b\\Zc\\z", end_anchor=marker).count(marker) == 2
    assert to_python("a\\z", end_anchor=marker) == "a\\Z"
    assert to_python("a$") != to_python("a$", end_anchor=marker)
