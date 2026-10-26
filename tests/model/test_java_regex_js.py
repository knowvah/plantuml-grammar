"""Tests for tools.model.java_regex_js: text rewrites, Node compilation, Java vectors."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.helpers.models import repo_resolved
from tests.model import jre_vectors as vectors
from tests.model.node_regex import Job, compiles_all, run_batch
from tools.model import ResolvedModel
from tools.model.java_regex import to_python
from tools.model.java_regex_js import (
    DOT,
    END_ANCHOR,
    LINE_TERMINATOR,
    JsRegexError,
    cp_text_js,
    line_pattern_js,
    literal_to_js,
    to_js,
)

MODEL_DIR = Path(__file__).resolve().parents[2] / "model"
EXCLUDED_CONSTRUCTS = ("(?(", "(?&")
NUMERIC_BACKREF = re.compile(r"\\[1-9]")
INLINE_CI = re.compile(r"\(\?-?i")
GROUP_NAME = re.compile(r"\(\?<(\w+)>")
MIN_MODEL_REGEXES = 900
MAX_CI_BACKREFS = 3
MIN_ATOMIC_LEAVES = 16
MIN_POSSESSIVE = 2
EMULATED_GROUP = "(?<_a"


def full(pattern: str, *, ci: bool = False) -> str:
    """Anchored full-match source for Node's ``test``."""
    return f"^(?:{to_js(pattern, ci=ci)})$"


def matches(pattern: str, text: str, *, ci: bool = False) -> bool:
    return run_batch([Job(full(pattern, ci=ci), [text])])[0].matches[0]


def test_dot_and_end_anchor_text() -> None:
    assert to_js("a.b") == f"a{DOT}b"
    assert DOT == "[^\\n\\r\\x85\\u2028\\u2029]"
    assert to_js("a$") == f"a{END_ANCHOR}"
    assert to_js("a\\Z") == f"a{END_ANCHOR}"
    assert to_js("a\\z") == "a$"
    assert END_ANCHOR == f"(?={LINE_TERMINATOR}?$)"


def test_case_insensitive_text_is_explicit_folding() -> None:
    assert to_js("a(?i:b)c") == "a(?:[bB])c"
    assert to_js("(?-i:a)b", ci=True) == "(?:a)[bB]"
    assert to_js("(?i)ab") == "[aA][bB]"
    assert to_js("(a(?i)b)c") == "(a[bB])c"
    assert to_js("[a-c]", ci=True) == "[A-Ca-c]"
    assert to_js("\\x41", ci=True) == "[aA]"
    assert to_js("\\x41") == "A"


def test_comment_is_dropped_and_named_groups_lose_their_names() -> None:
    assert to_js("a(?#note)b") == "ab"
    assert to_js("(?P<x>a)(?<y>b)") == "(?:a)(?:b)"
    assert to_js("(?<x>a)\\1") == "(a)\\1"
    assert to_js("(?<=a)b(?<!c)") == "(?<=a)b(?<!c)"


def test_lazy_quantifiers_and_repeats_pass_through() -> None:
    assert to_js("a+?b*?c??d{1,2}?e{2}") == "a+?b*?c??d{1,2}?e{2}"


def test_code_point_writer() -> None:
    assert cp_text_js(0x41) == "A"
    assert cp_text_js(0x5F) == "_"
    assert cp_text_js(0x22) == '"'
    assert cp_text_js(0x2E) == "\\."
    assert cp_text_js(0x2F) == "\\/"
    assert cp_text_js(0x2D) == "-"
    assert cp_text_js(0x2D, in_class=True) == "\\-"
    assert cp_text_js(0x20) == "\\x20"
    assert cp_text_js(0x0A) == "\\x0a"
    assert cp_text_js(0xE9) == "\\xe9"
    assert cp_text_js(0x2028) == "\\u2028"
    assert cp_text_js(0x1F600) == "\\u{1f600}"
    assert cp_text_js(0xD800) == "\\u{d800}"


def test_class_text_uses_only_legal_escapes() -> None:
    assert to_js("[\\w-]") == "[\\-0-9A-Z_a-z]"
    assert to_js("[\\.\\]\\^]") == "[\\.\\]\\^]"
    assert to_js("[\\p{Alpha}]") == "[A-Za-z]"
    assert to_js("[\\p{L}a]") == "[a\\p{L}]"
    assert to_js("[^\\d]") == "[^0-9]"
    assert to_js("\\D") == "[^0-9]"
    assert to_js("]}/") == "\\]\\}\\/"


def test_property_text() -> None:
    assert to_js("\\p{Lu}", ci=True) == "\\p{LC}"
    assert to_js("\\P{Ll}", ci=True) == "\\P{LC}"
    assert to_js("\\p{Lu}") == "\\p{Lu}"
    assert to_js("\\pL") == "\\p{L}"


def test_literal_to_js() -> None:
    # `\-` outside a class is a SyntaxError under `u`, so `-` stays bare here.
    assert literal_to_js("Ab-", ci=True) == "[aA][bB]-"
    assert literal_to_js("a.b") == "a\\.b"
    assert literal_to_js("\xe9 X", ci=True) == "\\xe9\\x20[xX]"
    assert literal_to_js("\U0001f600") == "\\u{1f600}"


def test_line_pattern_js_text() -> None:
    assert line_pattern_js("x") == f"^(?:x){LINE_TERMINATOR}?$"


@pytest.mark.parametrize(
    "pattern",
    ["[a[b]]", "[a&&b]", "\\h", "\\R", "\\Qa\\E", "(?s)a", "(?x:a)", "a\\", "[a", "[]", "[b-a]"],
)
def test_unsupported_java_syntax_raises(pattern: str) -> None:
    with pytest.raises(JsRegexError):
        to_js(pattern)


@pytest.mark.parametrize("pattern", ["[a\\", "\\p", "\\p{", "\\y", "\\cA", "\\x{41}", "(?<", "(?"])
def test_malformed_and_unknown_escapes_raise(pattern: str) -> None:
    with pytest.raises(JsRegexError):
        to_js(pattern)


@pytest.mark.parametrize(
    ("pattern", "message"),
    [
        ("(?|a)", "branch reset"),
        ("(?&n)", "expand"),
        ("(?1)", "expand"),
        ("(a)?(?(1)b|c)", "conditional"),
        ("a{,2}", "illegal repetition"),
        ("[\\1]", "class"),
    ],
)
def test_deferred_and_pcre_constructs_raise(pattern: str, message: str) -> None:
    with pytest.raises(JsRegexError, match=re.escape(message)):
        to_js(pattern)


def test_dot_and_escapes_in_node() -> None:
    cases = [
        (".", "\n", False),
        (".", "\x85", False),
        (".", "\u2028", False),
        (".", "\U0001f600", True),
        ("\\d", "7", True),
        ("\\d", "\u0663", False),
        ("\\w", "\xe9", False),
        ("\\s", "\x0b", True),
        ("\\s", "\xa0", False),
        ("\\D", "\u0663", True),
        ("[^\\w]", "\xe9", True),
        ("\\p{Alpha}", "\xe9", False),
        ("\\P{Alpha}", "\xe9", True),
        ("\\p{L}", "\xe9", True),
        ("\\p{Lu}", "a", False),
    ]
    outcomes = run_batch([Job(full(p), [t]) for p, t, _ in cases])
    assert [o.matches[0] for o in outcomes] == [want for *_, want in cases]


def test_case_folding_is_ascii_only_in_node() -> None:
    cases = [
        ("class", "ClAsS", True, True),
        ("class", "ClAsS", False, False),
        ("k", "\u212a", True, False),
        ("[a-z]", "\u212a", True, False),
        ("\xe9", "\xc9", True, False),
        ("\\p{Lu}", "a", True, True),
        ("a(?i:b)c", "aBc", False, True),
        ("a(?i:b)c", "aBC", False, False),
    ]
    jobs = [Job(full(p, ci=ci), [t]) for p, t, ci, _ in cases]
    assert [o.matches[0] for o in run_batch(jobs)] == [want for *_, want in cases]


def test_line_terminator_handling_in_node() -> None:
    body = to_js("title(.*)")
    out = run_batch([Job(line_pattern_js(body), ["title a", "title a\r\n", "title a\n\n", "x"])])
    assert out[0].matches == [True, True, False, False]
    dollar = run_batch([Job(f"^{to_js('a$')}", ["a\r\n", "a\n\n", "a\x85"])])
    assert dollar[0].matches == [True, False, True]
    absolute = to_js("a\\z")
    z_abs = run_batch([Job(f"^{absolute}", ["a", "a\n"])])
    assert z_abs[0].matches == [True, False]


def test_word_boundary_in_node() -> None:
    cases = [
        ("a\\bb", "a b"),
        ("a\\b", "a\xe9"),
        ("a\\b", "a\u0301"),
        ("a\\B", "a\u0301"),
        ("\\bab", "-ab"),
    ]
    jobs = [Job(to_js(p), [t]) for p, t in cases]
    assert [o.matches[0] for o in run_batch(jobs)] == [False, True, False, True, True]


def test_literal_to_js_in_node() -> None:
    jobs = [Job(f"^{literal_to_js('Ab-', ci=True)}$", ["aB-", "ab_"])]
    assert run_batch(jobs)[0].matches == [True, False]


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


def _translatable_model_sources() -> list[tuple[str, bool]]:
    seen: dict[tuple[str, bool], None] = {}
    for model in repo_resolved().values():
        for part in _leaves(model):
            source = str(part["regex"])
            if not any(marker in source for marker in EXCLUDED_CONSTRUCTS):
                seen[(source, bool(part.get("ci")))] = None
    return list(seen)


def _translate_or_ci_backref(source: str, ci: bool) -> str | None:
    """The translation, or ``None`` for a back reference under ci (D2 raises)."""
    try:
        return to_js(source, ci=ci)
    except JsRegexError as error:
        assert "(D2)" in str(error)
        assert ci
        return None


def test_every_model_regex_compiles_in_node() -> None:
    sources = _translatable_model_sources()
    assert len(sources) >= MIN_MODEL_REGEXES
    translated = [
        text
        for source, ci in sources
        for flag in (ci, not ci)
        if (text := _translate_or_ci_backref(source, flag)) is not None
    ]
    assert len(translated) >= 2 * len(sources) - MAX_CI_BACKREFS
    verdicts = compiles_all(translated)
    assert [t for t, ok in zip(translated, verdicts, strict=True) if not ok] == []
    assert not [t for t in translated if INLINE_CI.search(t)]
    for text in translated:
        for name in GROUP_NAME.findall(text):
            assert f"\\k<{name}>" in text


def test_model_has_atomic_and_possessive_leaves() -> None:
    pairs = _translatable_model_sources()
    assert sum("(?>" in source for source, _ in pairs) == MIN_ATOMIC_LEAVES
    possessive = [s for s, ci in pairs if "(?>" not in s and EMULATED_GROUP in to_js(s, ci=ci)]
    assert len(possessive) == MIN_POSSESSIVE


def _vector_source(case: vectors.Case) -> str | None:
    """The Node source for a vector case, or ``None`` for emulation plus numbered back reference."""
    try:
        body = to_js(case.pattern, ci=case.ci)
    except JsRegexError as error:
        assert "numbered back reference" in str(error)
        return None
    if case.mode == vectors.MODE_LINE:
        return line_pattern_js(body)
    return f"^(?:{body})$"


def _ci_backreference(case: vectors.Case) -> bool:
    """A numeric back reference where folding is on: D2 says translation raises."""
    return (case.ci or "(?i" in case.pattern) and NUMERIC_BACKREF.search(case.pattern) is not None


def test_ci_back_references_raise_per_d2() -> None:
    cases, _, _ = vectors.load()
    flagged = [c for c in cases if _ci_backreference(c)]
    assert flagged
    for case in flagged:
        with pytest.raises(JsRegexError, match="D2"):
            to_js(case.pattern, ci=case.ci)
    assert to_js("(a)\\1") == "(a)\\1"
    with pytest.raises(JsRegexError, match="D2"):
        to_js("(a)(?i:\\1)")


def test_vectors_match_java_reference_in_node() -> None:
    cases, strings, java = vectors.load()
    chosen = [
        (case, expected, source)
        for case, expected in zip(cases, java, strict=True)
        if not _ci_backreference(case) and (source := _vector_source(case)) is not None
    ]
    assert len(chosen) > 900
    outcomes = run_batch([Job(source, strings) for _, _, source in chosen])
    mismatches = []
    for (case, expected, source), outcome in zip(chosen, outcomes, strict=True):
        assert outcome.compiles, source
        wrong = [
            strings[i]
            for i, (got, want) in enumerate(zip(outcome.matches, expected, strict=True))
            if got != (want == "1") and vectors.comparable(case, strings[i])
        ]
        if wrong:
            mismatches.append((case, wrong[:3]))
    assert mismatches == []


def test_atomic_group_text() -> None:
    assert to_js("(?>a+)b") == "(?=(?<_a0>a+))\\k<_a0>b"
    assert to_js("(?>a(?>b))") == "(?=(?<_a0>a(?=(?<_a1>b))\\k<_a1>))\\k<_a0>"
    assert to_js("(?>a)*") == "(?=(?<_a0>a))\\k<_a0>*"


def test_possessive_quantifier_text() -> None:
    assert to_js("a*+b") == "(?=(?<_a0>a*))\\k<_a0>b"
    assert to_js("xa++") == "x(?=(?<_a0>a+))\\k<_a0>"
    assert to_js("a?+") == "(?=(?<_a0>a?))\\k<_a0>"
    assert to_js("a{2}+") == "(?=(?<_a0>a{2}))\\k<_a0>"
    assert to_js("a{2,}+") == "(?=(?<_a0>a{2,}))\\k<_a0>"
    assert to_js("(?:ab)*+c") == "(?=(?<_a0>(?:ab)*))\\k<_a0>c"
    assert to_js("[ab]{1,3}+") == "(?=(?<_a0>[ab]{1,3}))\\k<_a0>"
    assert to_js("(?>a)*+") == "(?=(?<_a1>(?=(?<_a0>a))\\k<_a0>*))\\k<_a1>"


def test_named_back_reference_text() -> None:
    assert to_js("(?P<x>a)(?P=x)") == "(?<x>a)\\k<x>"
    assert to_js("(?<x>a)\\k<x>+") == "(?<x>a)\\k<x>+"
    assert to_js("(?P<x>a)(?P<y>b)(?P=x)") == "(?<x>a)(?:b)\\k<x>"
    assert to_js("(?<x>a)\\k<x>(a)", ci=False) == "(?<x>a)\\k<x>(?:a)".replace("(?:a)", "(a)")


@pytest.mark.parametrize(
    ("pattern", "ci"),
    [("(?P<x>a)(?P=x)", True), ("(?<x>a)\\k<x>", True), ("(?<x>a)(?i:\\k<x>)", False)],
)
def test_named_back_reference_under_ci_raises(pattern: str, ci: bool) -> None:
    with pytest.raises(JsRegexError, match=r"\(D2\)"):
        to_js(pattern, ci=ci)


@pytest.mark.parametrize(
    "pattern",
    ["(?P<_a1>x)", "(?<_a>x)", "(?<_a1>x)\\k<_a1>", "(?P<x>a)(?P=_a0)"],
)
def test_generated_name_collision_raises(pattern: str) -> None:
    with pytest.raises(JsRegexError, match="collides"):
        to_js(pattern)


def test_duplicate_referenced_name_raises() -> None:
    with pytest.raises(JsRegexError, match="defined twice"):
        to_js("(?P<x>a)|(?P<x>b)(?P=x)")


@pytest.mark.parametrize("pattern", ["(a)(?>b)\\1", "(a)\\1c*+"])
def test_emulation_with_numbered_back_reference_raises(pattern: str) -> None:
    with pytest.raises(JsRegexError, match="numbered back reference"):
        to_js(pattern)


def test_atomic_and_possessive_in_node() -> None:
    cases = [
        ("(?>a+)a", "aaa", False),
        ("a*+b", "aaab", True),
        ("a*+a", "aaa", False),
        ("a++b", "aab", True),
        ("(?:ab)?+ab", "ab", False),
        ("a{1,2}+a", "aa", False),
        ("a{2,}+b", "aaab", True),
        ("(?>a|ab)c", "abc", False),
        ("(?:a|ab)(?>c|cd)", "abcd", False),
        ("(?:a|ab)(?>cd|c)", "abcd", True),
    ]
    outcomes = run_batch([Job(full(p), [t]) for p, t, _ in cases])
    assert [o.matches[0] for o in outcomes] == [want for *_, want in cases]
    py = [re.fullmatch(to_python(p), t) is not None for p, t, _ in cases]
    assert py == [want for *_, want in cases]


def test_named_back_reference_case_sensitivity_in_node() -> None:
    pattern = "(?P<x>a)(?P=x)"
    out = run_batch([Job(full(pattern), ["aa", "aA"])])
    assert out[0].matches == [True, False]
    assert [re.fullmatch(to_python(pattern), t) is not None for t in ("aa", "aA")] == [True, False]
