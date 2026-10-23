"""Tests for the TextMate emitter: regex flattening, grammar shape, PCRE portability.

PCRE check: the ``pcre2`` binding (PCRE2 10.x, installed with ``uv add --dev pcre2``) compiles
every emitted regex; the Oniguruma check lives in ``tests/textmate/tokenize.test.mjs``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pcre2
import pytest

from tools.emit import textmate
from tools.emit import textmate_regex as tmr
from tools.model import ResolvedModel
from tools.model.load import load_dir
from tools.model.resolve import resolve

ROOT = Path(__file__).resolve().parents[2]
MODEL_FIXTURES = ROOT / "tests" / "textmate" / "fixtures" / "model"
TOY = Path(__file__).parent / "fixtures" / "toy"
EMPTY = Path(__file__).parent / "fixtures" / "empty"
GENERATED = ROOT / "model" / "generated"
CLASS_SCOPE = "keyword.other.class"


def lit(text: str, ci: bool = False, scope: str | None = None) -> dict[str, Any]:
    part: dict[str, Any] = {"literal": text, "ci": ci}
    if scope:
        part["scope"] = scope
    return part


@pytest.fixture(scope="module")
def grammar() -> dict[str, Any]:
    return textmate.emit_textmate(resolve(load_dir(MODEL_FIXTURES)))


def model_with(contexts: dict[str, list[dict[str, Any]]]) -> ResolvedModel:
    return ResolvedModel("m", "diagram", None, "CLASS", {}, contexts)


def cmd(parts: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"command": "C", "kind": "single", "parts": parts, **extra}


# --- regex flattening ---------------------------------------------------------------


def test_scoped_named_part_maps_group_to_scope() -> None:
    part = {"seq": [{"regex": "\\w+", "name": "TYPE", "scope": CLASS_SCOPE}, {"regex": "\\s*"}]}
    regex, captures = tmr.flatten(part)
    assert regex == "(\\w+)\\s*"
    assert captures == {"1": {"name": "keyword.other.class.plantuml"}}


def test_unscoped_named_part_does_not_capture() -> None:
    regex, captures = tmr.flatten({"regex": "(?P<x>a)(b)", "name": "x"})
    assert (regex, captures) == ("(?:a)(?:b)", {})


def test_groups_are_numbered_left_to_right() -> None:
    part = {"seq": [lit("a", scope="s.a"), {"opt": lit("b", scope="s.b")}, lit("c", scope="s.c")]}
    regex, captures = tmr.flatten(part)
    assert regex == "(a)(?:(b))?(c)"
    assert list(captures) == ["1", "2", "3"]
    assert captures["3"] == {"name": "s.c.plantuml"}


@pytest.mark.parametrize(
    ("part", "expected"),
    [
        ({"alt": [lit("a"), lit("b")]}, "(?:a|b)"),
        ({"star": lit("a")}, "(?:a)*"),
        ({"plus": lit("a")}, "(?:a)+"),
        ({"opt": lit("a")}, "(?:a)?"),
        (lit("a.b(", ci=True), "(?i:a\\.b\\()"),
        ({"regex": "a|b"}, "(?:a|b)"),
    ],
)
def test_part_forms(part: dict[str, Any], expected: str) -> None:
    assert tmr.flatten(part)[0] == expected


def test_unknown_part_raises() -> None:
    with pytest.raises(ValueError, match="unknown Part"):
        tmr.flatten({"bogus": 1})


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("(a)", "(?:a)"),
        ("(?P<n>a)", "(?:a)"),
        ("(?<n>a)", "(?:a)"),
        ("(?'n'a)", "(?:a)"),
        ("(?:a)(?=b)(?<!c)", "(?:a)(?=b)(?<!c)"),
        ("\\(a\\)", "\\(a\\)"),
        ("[(a)]+(b)", "[(a)]+(?:b)"),
    ],
)
def test_demote_groups(pattern: str, expected: str) -> None:
    assert tmr.demote_groups(pattern) == expected


def test_flatten_alternatives_numbers_across_branches() -> None:
    regex, captures = tmr.flatten_alternatives([lit("}", scope="a"), lit(")", scope="b")])
    assert regex == "(?:(\\})|(\\)))"
    assert captures == {"1": {"name": "a.plantuml"}, "2": {"name": "b.plantuml"}}


# --- grammar shape ------------------------------------------------------------------


def test_top_level_metadata(grammar: dict[str, Any]) -> None:
    assert grammar["scopeName"] == "source.plantuml"
    assert grammar["fileTypes"] == ["puml", "plantuml", "pu", "iuml", "wsd"]


def test_one_block_per_start_keyword(grammar: dict[str, Any]) -> None:
    blocks = [p for p in grammar["patterns"] if "begin" in p]
    assert [b["begin"] for b in blocks] == [
        "^\\s*([@\\\\]start(?i:uml))",
        "^\\s*([@\\\\]start(?i:salt))",
        "^\\s*([@\\\\]start(?!(?:(?i:salt)|(?i:uml)))(?=[^\\r\\n])\\S*)",
    ]
    assert blocks[0]["patterns"][-1] == {"include": "#diagram_uml"}
    assert {"include": "#comments"} in blocks[1]["patterns"]
    assert {"include": "#preprocessor"} in blocks[1]["patterns"]


def test_unknown_start_word_block_is_last_and_opaque(grammar: dict[str, Any]) -> None:
    # PSystemUnsupported (PSystemBuilder.java:283-284): any body is accepted, so only comments
    # and the preprocessor are scoped inside; the block itself keeps the diagram scopes.
    other = [p for p in grammar["patterns"] if "begin" in p][-1]
    assert other["patterns"] == [{"include": "#comments"}, {"include": "#preprocessor"}]
    assert other["name"] == "meta.diagram.plantuml"
    assert other["beginCaptures"] == {"1": {"name": "keyword.control.start.plantuml"}}
    assert other["end"] == "^\\s*([@\\\\]end[A-Za-z0-9]*)"


def test_uml_union_deduplicates_identical_rules(grammar: dict[str, Any]) -> None:
    rules = grammar["repository"]["diagram_uml"]["patterns"]
    titles = [
        r
        for r in rules
        if r.get("captures", {}).get("1") == {"name": "keyword.other.plantuml"}
        and "title" in r["match"]
    ]
    assert len(titles) == 1
    assert len(rules) == 6  # title, class, link, note, package + participant


def test_class_rule_captures(grammar: dict[str, Any]) -> None:
    rules = grammar["repository"]["diagram_uml"]["patterns"]
    rule = next(r for r in rules if "(?i:class)" in r.get("match", ""))
    assert rule["captures"] == {
        "1": {"name": "keyword.other.plantuml"},
        "2": {"name": "entity.name.type.plantuml"},
        "3": {"name": "storage.modifier.stereotype.plantuml"},
        "4": {"name": "constant.other.color.plantuml"},
    }


def test_multiline_rule_uses_end_part(grammar: dict[str, Any]) -> None:
    rules = grammar["repository"]["diagram_uml"]["patterns"]
    note = next(r for r in rules if "(?i:note)" in r.get("begin", ""))
    assert note["end"] == "^\\s*(?i:end note)".replace("(?i:end note)", "((?i:end note))")
    assert note["endCaptures"] == {"1": {"name": "keyword.other.plantuml"}}
    assert "patterns" not in note


def test_push_rule_uses_pop_entry_as_end(grammar: dict[str, Any]) -> None:
    rules = grammar["repository"]["diagram_uml"]["patterns"]
    package = next(r for r in rules if "(?i:package)" in r.get("begin", ""))
    assert package["end"] == "(?:^\\s*(\\}))"
    assert package["endCaptures"] == {"1": {"name": "punctuation.definition.block.end.plantuml"}}
    assert package["patterns"] == [{"include": "#ctx_tm_class_pkg"}]
    pushed = grammar["repository"]["ctx_tm_class_pkg"]["patterns"]
    assert len(pushed) == 1  # the pop entry is the end, not a nested rule
    assert "(?i:item)" in pushed[0]["match"]


def test_preprocessor_and_comment_rules_are_fixed(grammar: dict[str, Any]) -> None:
    repo = grammar["repository"]
    assert repo["preprocessor"]["patterns"][0]["captures"]["1"]["name"] == (
        "keyword.control.directive.plantuml"
    )
    names = [p["name"] for p in repo["comments"]["patterns"]]
    assert names == ["comment.block.plantuml", "comment.line.apostrophe.plantuml"]


def test_json_is_deterministic_two_space_with_newline() -> None:
    resolved = resolve(load_dir(MODEL_FIXTURES))
    first = textmate.emit_textmate_json(resolved)
    assert first == textmate.emit_textmate_json(resolved)
    assert first.endswith("}\n")
    assert first.startswith('{\n  "name": "PlantUML",\n  "scopeName"')
    assert json.loads(first) == textmate.emit_textmate(resolved)


def test_empty_model_dir_has_no_blocks() -> None:
    grammar = textmate.emit_textmate(resolve(load_dir(EMPTY)))
    assert grammar["patterns"] == [{"include": "#comments"}]
    assert set(grammar["repository"]) == {"comments", "preprocessor"}


# --- entry rules on hand-built models -----------------------------------------------


def test_push_without_pop_ends_at_line_end() -> None:
    model = model_with({"main": [cmd(lit("go"), push="inner")], "inner": [cmd(lit("x"))]})
    repo: dict[str, Any] = {}
    rule = textmate._Rules(model, repo).entry_rule(model.contexts["main"][0])
    assert rule == {
        "begin": "go",
        "end": "$",
        "patterns": [{"include": "#ctx_m_inner"}],
    }
    assert repo["ctx_m_inner"] == {"patterns": [{"match": "x"}]}


def test_self_pushing_context_terminates() -> None:
    model = model_with({"main": [cmd(lit("a"), push="loop")], "loop": [cmd(lit("b"), push="loop")]})
    repo: dict[str, Any] = {}
    textmate._Rules(model, repo).entry_rule(model.contexts["main"][0])
    assert repo["ctx_m_loop"]["patterns"][0]["patterns"] == [{"include": "#ctx_m_loop"}]


def test_multiline_with_push_nests_context() -> None:
    entry = cmd(lit("{"), kind="multiline", end=lit("}"), push="body")
    model = model_with({"main": [entry], "body": [cmd(lit("x"))]})
    rule = textmate._Rules(model, {}).entry_rule(entry)
    assert rule["end"] == "\\}"
    assert rule["patterns"] == [{"include": "#ctx_m_body"}]


@pytest.mark.parametrize(("kind", "end"), [("multiline-bracket", "^\\s*\\}"), ("multiline", "$")])
def test_multiline_without_end_part_gets_default_end(kind: str, end: str) -> None:
    entry = cmd(lit("skinparam"), kind=kind)
    rule = textmate._Rules(model_with({"main": [entry]}), {}).entry_rule(entry)
    assert rule == {"begin": "skinparam", "end": end}


def test_pop_entry_outside_pushed_context_is_a_match() -> None:
    entry = cmd(lit("end"), pop=True)
    model = model_with({"main": [entry]})
    assert textmate._Rules(model, {}).context_rules([entry], skip_pop=False) == [{"match": "end"}]


# --- portability: every regex compiles under PCRE2 -----------------------------------


def all_regexes(grammar: dict[str, Any]) -> list[str]:
    return textmate.regexes(grammar)


@pytest.mark.parametrize("model_dir", [MODEL_FIXTURES, TOY], ids=["tm-fixtures", "toy"])
def test_every_regex_compiles_under_pcre2(model_dir: Path) -> None:
    found = all_regexes(textmate.emit_textmate(resolve(load_dir(model_dir))))
    assert len(found) >= 8
    for regex in found:
        pcre2.compile(regex)


def test_pcre2_rejects_invalid_regex() -> None:
    with pytest.raises(pcre2.PatternError):
        pcre2.compile("(unclosed")


def test_regexes_walker_collects_nested_keys() -> None:
    grammar = {
        "patterns": [{"match": "a"}, {"begin": "b", "end": "c", "patterns": [{"match": "d"}]}]
    }
    assert textmate.regexes(grammar) == ["a", "b", "c", "d"]


@pytest.mark.corpus
@pytest.mark.skipif(not any(GENERATED.glob("*.yaml")), reason="model/generated is empty")
def test_generated_models_emit_pcre_compilable_regexes() -> None:
    found = all_regexes(textmate.emit_textmate(resolve(load_dir(ROOT / "model"))))
    assert found
    for regex in found:
        pcre2.compile(regex)


# --- CLI ------------------------------------------------------------------------------


def test_main_writes_grammar(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "nested" / "g.json"
    code = textmate.main(["--model-dir", str(MODEL_FIXTURES), "--out", str(out)])
    assert code == textmate.EXIT_OK
    assert json.loads(out.read_text(encoding="utf-8"))["scopeName"] == "source.plantuml"
    assert capsys.readouterr().out.strip() == str(out)


def test_main_reports_model_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "x.yaml").write_text("schema_version: 2\n", encoding="utf-8")
    code = textmate.main(["--model-dir", str(bad), "--out", str(tmp_path / "o.json")])
    assert code == textmate.EXIT_ERROR
    assert "x.yaml" in capsys.readouterr().err
    assert not (tmp_path / "o.json").exists()


# --- rules that can match the empty string are never emitted ---------------------------


@pytest.mark.parametrize(
    ("pattern", "empty"),
    [
        (r"[\s\xa0]*", True),
        (r"(?i:[\s\xa0]*)(?i:\}?)", True),
        (r".*", True),
        (r"^$", True),
        (r"(?=a)", True),
        (r"a*b?", True),
        (r"a+", False),
        (r"(?i:class)\s+\w+", False),
        (r"\s*\}", False),
        (r"(?<=", True),  # unparsable: dropping is safe
    ],
)
def test_can_match_empty(pattern: str, empty: bool) -> None:
    assert tmr.can_match_empty(pattern) is empty


def test_nullable_match_and_begin_rules_are_not_emitted() -> None:
    nope = cmd({"regex": "[\\s\\xa0]*"})
    catch_all = cmd({"regex": ".*"})
    nullable_region = cmd({"regex": "\\s*"}, kind="multiline", end={"literal": "x", "ci": False})
    real = cmd({"seq": [lit("class", ci=True), {"regex": "\\s+\\w+"}]})
    model = model_with({"main": [nope, real, catch_all, nullable_region]})
    rules = textmate._Rules(model, {}).context_rules(model.contexts["main"], skip_pop=False)
    assert rules == [{"match": "(?i:class)\\s+\\w+"}]


def test_pop_end_of_a_pushed_context_may_stay_zero_width() -> None:
    entry = cmd(lit("package"), push="body")
    body = [cmd(lit("item")), cmd({"regex": "(?=\\})"}, pop=True)]
    model = model_with({"main": [entry], "body": body})
    (rule,) = textmate._Rules(model, {}).context_rules(model.contexts["main"], skip_pop=False)
    assert rule["begin"] == "package"
    assert rule["end"] == "(?:(?=\\}))"


PROBES = ["", "   ", "class Foo", "  note left of A : text", 'rule = "a" ; (* c *)', "a--b == c"]


def test_real_model_has_no_rule_that_matches_the_empty_string() -> None:
    import regex

    grammar = textmate.emit_textmate(resolve(load_dir(ROOT / "model")))
    patterns: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("match", "begin") and isinstance(value, str):
                    patterns.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(grammar["repository"])
    assert len(patterns) > 1000
    empty = []
    for pattern in patterns:
        try:
            compiled = regex.compile(pattern)
        except regex.error:
            continue  # Oniguruma-only syntax; compile portability is checked elsewhere
        for line in PROBES:
            for start in range(len(line) + 1):
                found = compiled.search(line, start)
                if found and found.end() == found.start():
                    empty.append(pattern)
                    break
            else:
                continue
            break
    assert empty == []
