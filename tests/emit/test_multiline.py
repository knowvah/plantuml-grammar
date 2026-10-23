"""Multiline commands end where upstream ends them (``tools.interp.scan``).

``CommandMultilines2`` closes a command at the first later line whose trimmed text matches
``end`` (``command/CommandMultilines2.java:79-110``), never at a later one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.interp import accepts
from tools.model.load import load_dir
from tools.model.resolve import resolve

MULTILINE = Path(__file__).parent / "fixtures" / "multiline"
START = "@startuml"
END = "@enduml"
ACCEPT = True
REJECT = False

CASES: list[tuple[tuple[str, ...], bool]] = [
    (("note", "x", "end note", "cmd"), ACCEPT),
    (("note", "end note"), ACCEPT),
    (("note", "x", "", "y", "  endnote  "), ACCEPT),
    (("note", "x", "end note", "end note"), REJECT),
    (("note", "endnote", "x", "end note"), REJECT),
    (("note", "x"), REJECT),
    (("note", "x", "end notes"), REJECT),
    (("note", "end notes", "end note"), ACCEPT),
    # a `{{ ... }}` embedded diagram is one unit; only its `}}` line is tested against end
    (("note", "{{", "end note", "}}", "end note"), ACCEPT),
    (("note", "{{", "{{", "end note", "}}", "end note", "}}", "end note"), ACCEPT),
    (("note", "{{json", "end note", "}}", "end note", "cmd"), ACCEPT),
    (("note", "  {{  ", ";", "  }}  ", "end note"), ACCEPT),
    (("note", "{{", "x", "}}", "}}", "end note"), ACCEPT),
    (("note", "{{", "x", "}}", "end note", "end note"), REJECT),
    (("note", "{{ json", "end note", "}}", "end note"), REJECT),
    (("note", "{{nojson", "end note", "}}", "end note"), REJECT),
]
IDS = [" / ".join(lines) for lines, _ in CASES]
# JsonDiagramFactory reads plain lines: the first end line closes, inside `{{` or not
PLAIN_CASES: list[tuple[tuple[str, ...], bool]] = [
    (("note", "x", "end note"), ACCEPT),
    (("note", "{{", "end note", "}}", "end note"), REJECT),
    (("note", "{{", "x", "}}", "end note"), ACCEPT),
]
PLAIN_IDS = [" / ".join(lines) for lines, _ in PLAIN_CASES]


def block(lines: tuple[str, ...], start: str = START, end: str = END) -> str:
    return "\n".join([start, *lines, end]) + "\n"


def plain_block(lines: tuple[str, ...]) -> str:
    return block(lines, "@startjson", "@endjson")


@pytest.fixture(scope="module")
def models():
    return resolve(load_dir(MULTILINE))


@pytest.mark.parametrize(("lines", "expected"), CASES, ids=IDS)
def test_interpreter_agrees_with_expectation(models, lines, expected: bool) -> None:
    assert accepts(models, block(lines))["accepted"] is expected


@pytest.mark.parametrize(("lines", "expected"), PLAIN_CASES, ids=PLAIN_IDS)
def test_plain_factory_interpreter_agrees(models, lines, expected: bool) -> None:
    assert accepts(models, plain_block(lines))["accepted"] is expected
