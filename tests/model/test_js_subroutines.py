"""Tests for ``tools.model.js_subroutines``: bounded expansion of DEFINE and ``(?&name)``."""

from __future__ import annotations

import hashlib
import sys
from functools import cache
from pathlib import Path

import pytest
import regex

from tests.model.node_regex import Job, run_batch
from tools.interp.source import split_block, split_blocks
from tools.model import js_subroutines as js
from tools.model.java_regex import to_python
from tools.model.java_regex_js import to_js
from tools.model.js_subroutines import (
    FAST_DEPTH,
    MAX_DEPTH,
    PATTERN_DEPTHS,
    Unsupported,
    depth_for,
    expand_subroutines,
    fast_depth,
    fast_final,
    native_kind,
)
from tools.model.load import parse_document
from tools.validate.corpus import enumerate_corpora

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures"
JOINER = ""
OBSERVED_DEPTH = 9
SLACK = 2
JSON_BLOCK, JSON_INVALID = "CO_JSON_BLOCK_BODY", "CO_JSON_DATA_INVALID"
WELL_FORMED, EMPTY, BALANCED = "RX_WELL_FORMED", "RX_EMPTY", "RX_BALANCED"
MODEL_PATTERNS = {
    JSON_BLOCK: "class-objects.yaml",
    JSON_INVALID: "class-objects.yaml",
    WELL_FORMED: "meta-diagrams-regex.yaml",
    EMPTY: "meta-diagrams-regex.yaml",
    BALANCED: "meta-diagrams-regex.yaml",
}
JSON_PATTERNS = {JSON_BLOCK, JSON_INVALID}
RX_PATTERNS = {WELL_FORMED, EMPTY, BALANCED}
EXPECTED_DEPTH = {JSON_BLOCK: 4, JSON_INVALID: 4, WELL_FORMED: 8, EMPTY: 3, BALANCED: 8}
JSON_DEPTH_LIMIT = 4
RECURSIVE_A = r"(?(DEFINE)(?<a>x(?&a)?y))(?&a)"


@cache
def model_pattern(name: str) -> str:
    text = (REPO / "model" / "diagrams" / MODEL_PATTERNS[name]).read_text()
    doc, errors = parse_document(text, MODEL_PATTERNS[name])
    assert doc is not None, errors
    return str(doc["variables"][name]["regex"])


@cache
def python_original(name: str) -> regex.Pattern[str]:
    return regex.compile(to_python(model_pattern(name)))


def python_expanded(pattern: str, depth: int) -> regex.Pattern[str]:
    return regex.compile(to_python(expand_subroutines(pattern, depth)))


def matches(pattern: str, text: str) -> bool:
    return regex.fullmatch(pattern, text) is not None


def nested_objects(k: int) -> str:
    return '"a":' + '{"a":' * k + "1" + "}" * k


def nested_parens(k: int) -> str:
    return "(" * k + "a" + ")" * k


# --- unit: expansion semantics -------------------------------------------------------


def test_pattern_without_define_is_returned_unchanged():
    pattern = r"a(?<n>b)+(?&n)?"
    assert expand_subroutines(pattern) == pattern


def test_recursive_definition_expands_to_the_depth():
    expanded = expand_subroutines(RECURSIVE_A, 3)

    assert "(?&" not in expanded
    assert "DEFINE" not in expanded
    assert [matches(expanded, t) for t in ("xy", "xxyy", "xxxyyy", "xxxxyyyy")] == [
        True,
        True,
        True,
        False,
    ]


def test_non_recursive_calls_inline_exactly():
    pattern = r"(?(DEFINE)(?<d>\d+)(?<s>[-+]))(?&d)(?&s)(?&d)"
    assert expand_subroutines(pattern) == r"(?:\d+)(?:[-+])(?:\d+)"


def test_deepest_call_becomes_a_quantifiable_never_match():
    expanded = expand_subroutines(r"(?(DEFINE)(?<a>x(?&a)))(?&a)", 2)
    assert expanded == r"(?:x(?:x(?:(?!))))"


def test_mutual_recursion_counts_each_name_separately():
    pattern = r"(?(DEFINE)(?<p>\((?&q)?\))(?<q>\[(?&p)?\]))(?&p)"
    expanded = expand_subroutines(pattern, 2)

    assert [matches(expanded, t) for t in ("()", "([])", "([()])", "([([])])", "([([()])])")] == [
        True,
        True,
        True,
        True,
        False,
    ]


def test_named_groups_in_definitions_are_demoted():
    pattern = r"(?(DEFINE)(?<d>(?<inner>\d)+))(?&d)-(?&d)"
    assert expand_subroutines(pattern) == r"(?:(?:\d)+)-(?:(?:\d)+)"


def test_named_group_outside_define_is_kept():
    pattern = r"(?(DEFINE)(?<d>\d))(?<keep>a)(?&d)"
    assert expand_subroutines(pattern) == r"(?<keep>a)(?:\d)"


@pytest.mark.parametrize(
    "reference", [r"\k<inner>", r"(?P=inner)", r"(?&inner)", r"\g<inner>", r"(?P>inner)"]
)
def test_reference_to_a_demoted_group_is_unsupported(reference):
    pattern = rf"(?(DEFINE)(?<d>(?<inner>a)))(?&d){reference}"
    with pytest.raises(Unsupported, match="inner"):
        expand_subroutines(pattern)


def test_escaped_and_classed_calls_are_left_alone():
    pattern = r"(?(DEFINE)(?<a>b))\(?&a)[(?&a)]\\(?&a)"
    assert expand_subroutines(pattern) == r"\(?&a)[(?&a)]\\(?:b)"


def test_nested_class_does_not_hide_the_group_end():
    pattern = r"(?(DEFINE)(?<a>[a[b]]c))(?&a)"
    assert expand_subroutines(pattern) == r"(?:[a[b]]c)"


@pytest.mark.parametrize(
    ("pattern", "reason"),
    [
        (r"(?(DEFINE)(?<a>x))(?(DEFINE)(?<b>y))", "more than one"),
        (r"(?(DEFINE)(?<a>x)y)", "other than a named group"),
        (r"(?(DEFINE)(?<a>x)(?<a>y))", "appears twice"),
        (r"(?(DEFINE)(?<a>x))(?&b)", "undefined subroutine b"),
        (r"(?(DEFINE)(?<a>x)", "unclosed group"),
        (r"(?(DEFINE)(?<a>[x))", "unclosed character class"),
    ],
)
def test_malformed_define_is_unsupported(pattern, reason):
    with pytest.raises(Unsupported, match=reason) as info:
        expand_subroutines(pattern)
    assert reason in info.value.reason


def test_expansion_over_the_size_cap_is_unsupported():
    pattern = r"(?(DEFINE)(?<a>x(?&a)?(?&a)?))(?&a)"
    assert len(expand_subroutines(pattern, 10)) < js.MAX_EXPANDED_BYTES
    with pytest.raises(Unsupported, match=str(js.MAX_EXPANDED_BYTES)):
        expand_subroutines(pattern, 20)


# --- model patterns: boundaries, fallback and Node ------------------------------------


def test_balanced_boundary_is_one_below_max_depth():
    expanded = python_expanded(model_pattern(BALANCED), MAX_DEPTH)
    assert expanded.fullmatch(nested_parens(MAX_DEPTH - 1)) is not None
    assert expanded.fullmatch(nested_parens(MAX_DEPTH)) is None
    assert python_original(BALANCED).fullmatch(nested_parens(MAX_DEPTH)) is not None


def test_json_block_boundary_at_four():
    expanded = python_expanded(model_pattern(JSON_BLOCK), JSON_DEPTH_LIMIT)
    ks = (JSON_DEPTH_LIMIT - 2, JSON_DEPTH_LIMIT - 1, JSON_DEPTH_LIMIT)

    assert [expanded.fullmatch(nested_objects(k)) is not None for k in ks] == [True, True, False]
    assert python_original(JSON_BLOCK).fullmatch(nested_objects(JSON_DEPTH_LIMIT)) is not None


@pytest.mark.parametrize("name", sorted(JSON_PATTERNS))
def test_json_patterns_are_unsupported_at_max_depth(name):
    with pytest.raises(Unsupported, match="bytes"):
        expand_subroutines(model_pattern(name), MAX_DEPTH)


@pytest.mark.parametrize("name", sorted(MODEL_PATTERNS))
def test_depth_for_each_model_pattern(name):
    assert depth_for(model_pattern(name)) == EXPECTED_DEPTH[name]


def test_depth_for_unknown_pattern_is_max_depth():
    assert depth_for("a(?(DEFINE)(?<b>c))") == MAX_DEPTH


def test_fast_depth_is_four():
    assert FAST_DEPTH == 4


@pytest.mark.parametrize("name", sorted(MODEL_PATTERNS))
def test_default_depth_expands_under_the_cap(name):
    expanded = expand_subroutines(model_pattern(name))
    assert expanded == expand_subroutines(model_pattern(name), EXPECTED_DEPTH[name])
    assert len(expanded.encode()) < js.MAX_EXPANDED_BYTES
    assert "(?&" not in expanded


def test_depth_table_keys_match_the_yaml_sources():
    digests = {hashlib.sha256(model_pattern(n).encode()).hexdigest() for n in MODEL_PATTERNS}
    assert digests == set(PATTERN_DEPTHS)


def test_native_kind_and_fast_final():
    assert native_kind(model_pattern(JSON_BLOCK)) == "json-block-body"
    assert native_kind(model_pattern(JSON_INVALID)) == "json-data-invalid"
    assert native_kind(model_pattern(WELL_FORMED)) == "regex-well-formed"
    assert [native_kind(model_pattern(n)) for n in (EMPTY, BALANCED)] == [None, None]
    assert fast_final(model_pattern(JSON_BLOCK)) == "accept"
    assert fast_final(model_pattern(JSON_INVALID)) == "reject"
    assert fast_final(model_pattern(WELL_FORMED)) == "accept"
    assert fast_depth(model_pattern(JSON_BLOCK)) == FAST_DEPTH
    assert fast_depth(model_pattern(WELL_FORMED)) is None
    with pytest.raises(ValueError, match="not a native"):
        fast_depth(model_pattern(EMPTY))
    with pytest.raises(ValueError, match="not a native"):
        fast_final(model_pattern(EMPTY))


def test_max_depth_is_observed_depth_plus_slack():
    assert MAX_DEPTH == OBSERVED_DEPTH + SLACK


def test_expansions_compile_in_node():
    cases = EXPECTED_DEPTH
    jobs = [Job(to_js(expand_subroutines(model_pattern(n), d))) for n, d in cases.items()]
    outcomes = run_batch(jobs)

    assert {n: o.compiles for n, o in zip(cases, outcomes, strict=True)} == dict.fromkeys(
        cases, True
    )


# --- corpus: measure MAX_DEPTH and compare against the original -----------------------


def bracket_depth(text: str) -> int:
    """Deepest ``{`` / ``[`` nesting outside JSON strings."""
    depth = deepest = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            quoted, escaped = (char != '"' or escaped), (char == "\\" and not escaped)
        elif char == '"':
            quoted = True
        elif char in "{[":
            depth += 1
            deepest = max(deepest, depth)
        elif char in "}]":
            depth -= 1
    return deepest


def paren_depth(text: str) -> int:
    """Deepest unescaped ``(`` nesting (classes are not skipped: text may be malformed)."""
    depth = deepest = 0
    escaped = False
    for char in text:
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "(":
            depth += 1
            deepest = max(deepest, depth)
        elif char == ")":
            depth -= 1
    return deepest


def json_candidates(lines: list[str]) -> set[str]:
    found: set[str] = set()
    for i, line in enumerate(lines):
        found.add(line)
        found.update(line[k:] for k, char in enumerate(line) if char in "{[")
        if line.endswith("{"):
            for j in range(i + 1, min(len(lines), i + 300)):
                if lines[j] == "}":
                    body = JOINER.join(lines[i + 1 : j])
                    found.update((body, body + JOINER))
    return found


def collect_candidates(paths: list[Path]) -> tuple[set[str], set[str]]:
    """Lines that can reach the JSON commands and the regex-diagram commands."""
    json_lines: set[str] = set()
    regex_lines: set[str] = set()
    for path in paths:
        text = path.read_text(errors="replace")
        wants_json = "json" in text.lower() or "{" in text
        wants_regex = "startregex" in text.lower()
        if not (wants_json or wants_regex):
            continue
        for block in split_blocks(text):
            body = split_block(block).body
            if wants_regex and "regex" in block.lower():
                for line in body:
                    regex_lines.update((line.text, line.text.lstrip(" \t")))
            json_lines |= json_candidates([line.trimmed for line in body])
    return json_lines, regex_lines


@pytest.fixture(scope="module")
def candidates() -> dict[str, set[str]]:
    paths = sorted(FIXTURES.rglob("*.puml")) + [p for _, p, _ in enumerate_corpora()]
    json_lines, regex_lines = collect_candidates(paths)
    return {
        JSON_BLOCK: json_lines,
        JSON_INVALID: json_lines,
        WELL_FORMED: regex_lines,
        EMPTY: regex_lines,
        BALANCED: regex_lines,
    }


def disagreements(name: str, depth: int, lines: set[str]) -> list[str]:
    original, expanded = python_original(name), python_expanded(model_pattern(name), depth)
    return [s for s in lines if (original.fullmatch(s) is None) != (expanded.fullmatch(s) is None)]


@pytest.mark.corpus
def test_measured_depth_equals_the_recorded_observation(candidates):
    hits = {n: {s for s in candidates[n] if python_original(n).fullmatch(s)} for n in candidates}
    json_depth = max(bracket_depth(s) for s in hits[JSON_BLOCK]) + 1
    regex_depth = max(paren_depth(s) for s in hits[WELL_FORMED] | hits[BALANCED]) + 1

    assert max(json_depth, regex_depth) == OBSERVED_DEPTH
    assert (json_depth, regex_depth) == (OBSERVED_DEPTH, 6)
    print("hits per pattern:", {n: len(h) for n, h in hits.items()}, file=sys.stderr)


@pytest.mark.corpus
def test_buildable_patterns_are_tight_at_their_observed_depth(candidates):
    assert disagreements(JSON_INVALID, 4, candidates[JSON_INVALID]) == []
    assert disagreements(JSON_INVALID, 3, candidates[JSON_INVALID]) != []
    assert disagreements(WELL_FORMED, 6, candidates[WELL_FORMED]) == []
    assert disagreements(WELL_FORMED, 5, candidates[WELL_FORMED]) != []
    assert disagreements(BALANCED, 6, candidates[BALANCED]) == []
    assert disagreements(BALANCED, 5, candidates[BALANCED]) != []


@pytest.mark.corpus
@pytest.mark.parametrize("name", sorted(RX_PATTERNS))
def test_regex_expansion_at_depth_for_agrees_with_the_original(name, candidates):
    assert disagreements(name, depth_for(model_pattern(name)), candidates[name]) == []


@pytest.mark.corpus
def test_fast_path_answer_is_final_in_its_direction(candidates):
    """Depth-4 accept implies original accept (block); depth-4 reject implies reject (invalid)."""
    block = disagreements(JSON_BLOCK, FAST_DEPTH, candidates[JSON_BLOCK])
    invalid = disagreements(JSON_INVALID, FAST_DEPTH, candidates[JSON_INVALID])
    original_block = python_original(JSON_BLOCK)
    fast_block = python_expanded(model_pattern(JSON_BLOCK), FAST_DEPTH)
    original_invalid = python_original(JSON_INVALID)
    fast_invalid = python_expanded(model_pattern(JSON_INVALID), FAST_DEPTH)

    assert block != []  # the bounded block body does lose deep corpus text
    assert invalid == []
    for s in candidates[JSON_BLOCK]:
        if fast_block.fullmatch(s):
            assert original_block.fullmatch(s)
    for s in candidates[JSON_INVALID]:
        if not fast_invalid.fullmatch(s):
            assert not original_invalid.fullmatch(s)
    assert all(original_block.fullmatch(s) and not fast_block.fullmatch(s) for s in block)
