"""Emitters drop ``reject`` entries and ``join`` entries that need the U+E100 joiner."""

from __future__ import annotations

from typing import Any

import pytest

from tools.emit import textmate
from tools.emit.skip import JOINER, needs_joiner, skipped
from tools.model import Entry, ResolvedModel, ResolvedModels

KEEP = "keepme"
DROP = "dropme"


def rx(pattern: str) -> dict[str, Any]:
    return {"regex": pattern}


@pytest.mark.parametrize(
    ("part", "expected"),
    [
        ({"literal": JOINER, "ci": False}, True),
        ({"literal": "ab", "ci": False}, False),
        (rx(f".*{JOINER}.*"), True),
        (rx(f"a{JOINER}"), True),
        (rx(f"(?:{JOINER})"), False),  # nested groups are not analysed: kept (conservative)
        (rx(f"a{JOINER}?"), False),
        (rx(f"a{JOINER}*"), False),
        (rx(f"a{JOINER}{{0,2}}"), False),
        (rx(f"a{JOINER}+"), True),
        (rx(f"a{JOINER}{{1,2}}"), True),
        (rx(f"[^{JOINER}]+"), False),
        (rx(f"a|{JOINER}"), False),
        (rx(f"\\{JOINER}"), True),  # escaped literal U+E100
        (rx("\\" + JOINER + "?"), False),
        (rx(f"\\\\{JOINER}"), True),
        (rx(f"a\\|{JOINER}"), True),  # an escaped '|' is no alternation
        (rx(f"\\({JOINER}"), True),  # an escaped '(' opens no group
        (rx(f"[(|]{JOINER}"), True),  # metacharacters inside a class are members
        (rx(f"(a|b){JOINER}"), True),
        (rx(f"(a|{JOINER})b"), False),
        (rx(f"x[a{JOINER}]"), False),
        (rx(f"x[]{JOINER}]y{JOINER}"), True),
        (rx("abc"), False),
        ({"seq": [rx("a"), rx(f"b{JOINER}")]}, True),
        ({"seq": [rx("a"), rx("b")]}, False),
        ({"alt": [rx(f"a{JOINER}"), rx(f"b{JOINER}")]}, True),
        ({"alt": [rx(f"a{JOINER}"), rx("b")]}, False),
        ({"alt": []}, False),
        ({"opt": rx(f"a{JOINER}")}, False),
        ({"star": rx(f"a{JOINER}")}, False),
        ({"plus": rx(f"a{JOINER}")}, True),
    ],
)
def test_needs_joiner(part: dict[str, Any], expected: bool) -> None:
    assert needs_joiner(part) is expected


def entry(parts: dict[str, Any], **extra: Any) -> Entry:
    return {"command": "C", "kind": "single", "parts": parts, **extra}


def test_skipped_covers_reject_and_joiner_joins_only() -> None:
    joiner = rx(f"a{JOINER}b")
    assert skipped(entry(rx("x"), reject=True)) is True
    assert skipped(entry(joiner, kind="multiline", join={"max_lines": 2})) is True
    assert skipped(entry(joiner)) is False  # not a join entry: kept as is
    assert skipped(entry(rx("x"), kind="multiline", join={"max_lines": 2})) is False
    assert skipped(entry(rx("x"))) is False


def model() -> ResolvedModels:
    main: list[Entry] = [
        {**entry(rx(KEEP)), "command": "Keep"},
        {**entry(rx(DROP), reject=True), "command": "Rejected"},
        {
            **entry(rx(f"{DROP}2{JOINER}x"), kind="multiline", join={"max_lines": 3}),
            "command": "Joined",
        },
        {**entry(rx(f"{KEEP}2"), kind="multiline", join={"max_lines": 3}), "command": "Join1"},
    ]
    return {"m": ResolvedModel("m", "diagram", None, "CLASS", {}, {"main": main})}


def test_textmate_drops_skipped_entries() -> None:
    grammar = textmate.emit_textmate_json(model())
    assert KEEP in grammar and f"{KEEP}2" in grammar
    assert DROP not in grammar


def test_textmate_drops_skipped_pop_end_too() -> None:
    ctx_entries: list[Entry] = [
        entry(rx("open"), push="body"),
    ]
    body = [
        entry(rx(f"a{JOINER}"), kind="multiline", join={"max_lines": 1}, pop=True),
        entry(rx("close"), pop=True),
    ]
    resolved = {
        "m": ResolvedModel("m", "diagram", None, "CLASS", {}, {"main": ctx_entries, "body": body})
    }
    grammar = textmate.emit_textmate(resolved)
    ends = [r for r in textmate.regexes(grammar) if "close" in r]
    assert ends and not any(JOINER in r for r in textmate.regexes(grammar))


HEAD = rx("class \\w+")
BRACE = {"literal": "{", "ci": False}
JOIN_LITERAL = {"literal": JOINER, "ci": False}


def join_entry(parts: dict[str, Any], max_lines: int = 1, **extra: Any) -> Entry:
    return entry(parts, kind="multiline", join={"max_lines": max_lines}, **extra)
