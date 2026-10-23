"""Emitters honour regex ``ci``, ``join`` and ``end``-less ``multiline-bracket`` entries."""

from __future__ import annotations

from pathlib import Path

import pcre2
import pytest

from tools.emit import textmate
from tools.model import ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve

CONTRACT = Path(__file__).parent / "fixtures" / "contract"


@pytest.fixture(scope="module")
def models() -> ResolvedModels:
    return resolve(load_dir(CONTRACT))


def uml(*lines: str) -> str:
    return "\n".join(["@startuml", *lines, "@enduml"]) + "\n"


# --- textmate -----------------------------------------------------------------------------


def _rules(models: ResolvedModels) -> list[dict[str, object]]:
    grammar = textmate.emit_textmate(models)
    return grammar["repository"]["diagram_uml"]["patterns"]


def test_textmate_regex_ci_wraps_and_absent_does_not(models: ResolvedModels) -> None:
    matches = [r.get("match") for r in _rules(models)]
    assert matches[0] == "(?i:abc)"
    assert matches[1] == "xyz"
    assert pcre2.compile("(?i:abc)").match("ABC") is not None


def test_textmate_join_is_a_single_line_match(models: ResolvedModels) -> None:
    rule = _rules(models)[2]
    assert "begin" not in rule
    assert rule["match"] == "(?i:wrap)\\s+\\w+(?:\ue100\\w+)?"


def test_textmate_bracket_without_end_keeps_the_default_end(models: ResolvedModels) -> None:
    rule = _rules(models)[3]
    assert rule["end"] == "^\\s*\\}"
    assert rule["begin"] == "(?i:pkg)\\s+\\w+\\s*\\{"
