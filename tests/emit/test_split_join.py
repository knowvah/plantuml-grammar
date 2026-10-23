"""A ``join`` whose U+E100s are all top-level ``seq`` literals: one segment per line.

Upstream joins up to ``max_lines`` + 1 lines with U+E100 and matches ``parts`` against the
result (``tools.interp.scan.scan_join``). When ``parts`` is a ``seq`` holding exactly
``max_lines`` U+E100 literals, the joined text can only have that many joiners, each taken by
one literal, so line *n* matches the *n*-th segment whole. TextMate, which matches one line
at a time, drops the entry.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.emit import textmate
from tools.emit.skip import JOINER
from tools.interp import accepts
from tools.model.load import load_dir
from tools.model.resolve import resolve

SPLIT_JOIN = Path(__file__).parent / "fixtures" / "split_join"
ACCEPT = True
REJECT = False

CASES: list[tuple[tuple[str, ...], bool]] = [
    (("class a", "{", "}"), ACCEPT),
    (("class a  ", "  {  ", "x", "}"), ACCEPT),
    (("class a {", "}"), ACCEPT),
    (("class a",), ACCEPT),
    (("class a", "{", "}", "class b", "{", "x", "}"), ACCEPT),
    # a blank line breaks the join: `{` alone is then no command
    (("class a", "", "{", "}"), REJECT),
    # line 2 must be `{` whole
    (("class a", "{ x", "}"), REJECT),
    (("class a", "{"), REJECT),
    (("{", "}"), REJECT),
]
IDS = [" / ".join(map(repr, lines)) for lines, _ in CASES]


def block(lines: tuple[str, ...]) -> str:
    return "\n".join(["@startuml", *lines, "@enduml"]) + "\n"


@pytest.fixture(scope="module")
def models():
    return resolve(load_dir(SPLIT_JOIN))


@pytest.mark.parametrize(("lines", "expected"), CASES, ids=IDS)
def test_interpreter_agrees_with_expectation(models, lines, expected: bool) -> None:
    assert accepts(models, block(lines))["accepted"] is expected


def test_textmate_still_drops_the_join(models) -> None:
    regexes = textmate.regexes(textmate.emit_textmate(models))
    assert not any(JOINER in r for r in regexes)
