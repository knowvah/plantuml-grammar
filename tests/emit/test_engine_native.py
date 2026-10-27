"""Engine patterns: the D2 ES2018 baseline scanner and the D3a native JSON splits."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest

from tests.emit.engine_support import (
    JSON_COMMANDS,
    PIN,
    engine_entries,
    entry,
    lit,
    rx,
    synthetic,
)
from tests.model.test_js_subroutines import JSON_BLOCK, model_pattern
from tools.emit import engine as eng
from tools.model.java_regex_js import LINE_TERMINATOR, line_pattern_js

# --- D2 baseline ---------------------------------------------------------------------------

MODIFIER = re.compile(r"\(\?(?:[imsx]+-?[imsx]*|-[imsx]+)[:)]")
GROUP_NAME = re.compile(r"\(\?<([A-Za-z_]\w*)>")


def scan_pattern(source: str) -> Iterator[str]:
    """Yield a finding per modifier group, duplicate group name or v-mode class syntax."""
    names: set[str] = set()
    i, in_class, n = 0, False, len(source)
    while i < n:
        char = source[i]
        if char == "\\":
            if in_class and source.startswith("\\q{", i):
                yield "\\q{"
            i += 2
            continue
        if in_class:
            if source.startswith(("--", "&&"), i):
                yield source[i : i + 2]
            in_class = char != "]"
        elif char == "[":
            in_class = True
        elif char == "(":
            yield from group_findings(source, i, names)
        i += 1


def group_findings(source: str, at: int, names: set[str]) -> Iterator[str]:
    if MODIFIER.match(source, at):
        yield "modifier"
    named = GROUP_NAME.match(source, at)
    if named:
        if named.group(1) in names:
            yield f"duplicate group {named.group(1)}"
        names.add(named.group(1))


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("(?i:a)", ["modifier"]),
        ("(?-i)a", ["modifier"]),
        ("(?m)(?s:a)", ["modifier", "modifier"]),
        ("(?<a>x)(?<a>y)", ["duplicate group a"]),
        ("[a--b]", ["--"]),
        ("[a&&b]", ["&&"]),
        ("[\\q{ab}]", ["\\q{"]),
        ("\\(?i:a)", []),
        ("[(?i:]x(?<a>1)(?:2)", []),
        ("a--b(?=x)(?<=y)", []),
    ],
)
def test_baseline_scanner_finds_what_it_should(source, expected):
    assert list(scan_pattern(source)) == expected


def test_engine_patterns_stay_in_the_es2018_baseline(built):
    findings = [
        (i, key, f)
        for i, p in enumerate(built["patterns"])
        for key in ("source", "guard")
        if key in p
        for f in scan_pattern(p[key])
    ]
    assert any("guard" in p for p in built["patterns"])
    assert findings == []


# --- native JSON splits (D3a) --------------------------------------------------------------

BLOCK = model_pattern(JSON_BLOCK)


def split_of(data: dict[str, Any], pid: int) -> dict[str, Any]:
    return data["patterns"][pid]["split"]


def test_optional_native_leaf_is_distributed_into_any():
    part = {"seq": [lit("a"), {"opt": {"seq": [rx(BLOCK), lit("b")]}}, lit("c")]}
    data = eng.build_engine(synthetic([entry(part)]), PIN)
    start = data["patterns"][data["context_table"][0][0]["start"]]
    plain, split_id = (data["patterns"][i] for i in start["any"])
    assert plain["source"] == line_pattern_js("(?:(?:a)(?:c))")
    split = split_of(data, start["any"][1])
    assert split["native"] == "json-block-body" and split["fast_final"] == "accept"
    head, tail, fast = (data["patterns"][split[k]] for k in ("head", "tail", "fast"))
    assert head == {"source": "(?<=^(?:(?:(?:a))))", "flags": "uy"}
    assert tail == {"source": f"(?:(?:(?:b)(?:c))){LINE_TERMINATOR}?$", "flags": "uy"}
    assert fast["flags"] == "u" and fast["source"].startswith("^(?:(?:(?:a)")
    assert "split" in split_id


def test_alt_of_native_and_plain_alternatives():
    part = {"alt": [rx(BLOCK), lit("z")]}
    data = eng.build_engine(synthetic([entry(part)]), PIN)
    start = data["patterns"][data["context_table"][0][0]["start"]]
    kinds = ["split" if "split" in data["patterns"][i] else "source" for i in start["any"]]
    assert kinds == ["split", "source"]


def test_single_native_alternative_is_a_bare_split():
    data = eng.build_engine(synthetic([entry({"seq": [lit("x"), rx(BLOCK)]})]), PIN)
    start = data["context_table"][0][0]["start"]
    assert set(data["patterns"][start]) - {"guard"} == {"split"}
    assert data["patterns"][split_of(data, start)["tail"]]["source"].startswith("(?:(?:))")


@pytest.mark.parametrize("quantifier", ["star", "plus"])
def test_native_leaf_under_a_repeat_is_an_error(quantifier):
    with pytest.raises(eng.EngineBuildError, match="star or plus"):
        eng.build_engine(synthetic([entry({quantifier: rx(BLOCK)})]), PIN)


def test_two_native_leaves_in_one_alternative_are_an_error():
    with pytest.raises(eng.EngineBuildError, match="more than one"):
        eng.build_engine(synthetic([entry({"seq": [rx(BLOCK), rx(BLOCK)]})]), PIN)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (rx("(?>a+)"), lit("")),
        (lit(""), rx("(?>a+)")),
        (rx("(?<n>a)\\k<n>"), lit("")),
        (lit(""), rx("(?<n>a)\\k<n>")),
    ],
)
def test_head_or_tail_with_atomic_or_backreference_is_an_error(before, after):
    part = {"seq": [before, rx(BLOCK), after]}
    with pytest.raises(eng.EngineBuildError, match="atomic group or a back reference"):
        eng.build_engine(synthetic([entry(part)]), PIN)


def test_real_json_commands_are_splits(resolved, built):
    found: dict[str, set[str]] = {c: set() for c in JSON_COMMANDS}
    for mid, name, index, source in engine_entries(resolved, built):
        if source["command"] in found:
            out = built["context_table"][built["models"][mid]["contexts"][name]][index]
            pattern = built["patterns"][out["start"]]
            found[source["command"]].add("any" if "any" in pattern else next(iter(pattern)))
    assert found == {
        "CommandCreateJsonBlock": {"any"},
        "CommandCreateJsonSingleLineError": {"split"},
    }


def test_regex_well_formed_is_a_split_without_a_fast_regex(resolved, built):
    found = []
    for mid, name, index, source in engine_entries(resolved, built):
        if source["command"] == "RegexLineWellFormed":
            out = built["context_table"][built["models"][mid]["contexts"][name]][index]
            pattern = built["patterns"][out["start"]]
            assert set(pattern) - {"guard"} == {"split"}
            found.append(pattern["split"])
    assert len(found) == 1
    split = found[0]
    assert (split["native"], split["fast"], split["fast_final"]) == (
        "regex-well-formed",
        None,
        "accept",
    )
    assert len(built["patterns"][split["head"]]["source"]) < 200
