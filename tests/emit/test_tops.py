"""Emitters render only the top model of each factory (a family replaces its base)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.emit import tops
from tools.emit.textmate import emit_textmate_json
from tools.model import ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve

FAMILY = Path(__file__).parent / "fixtures" / "family"
BASE_ID = "gen-seq"
TOP_ID = "seq"
LOOSE_ID = "loose"
REMOVED = "gone"
ACCEPT = "ok"
REJECT = "reject"


@pytest.fixture(scope="module")
def models() -> ResolvedModels:
    return resolve(load_dir(FAMILY))


def uml_text(*lines: str) -> str:
    return "\n".join(["@startuml", *lines, "@enduml"]) + "\n"


def test_emitted_diagrams_are_tops_and_factoryless_models(models: ResolvedModels) -> None:
    assert [m.id for m in tops.emitted_diagrams(models)] == [LOOSE_ID, TOP_ID]


def test_without_the_family_the_base_is_the_top(models: ResolvedModels) -> None:
    stripped = {k: v for k, v in models.items() if k != TOP_ID}
    assert [m.id for m in tops.emitted_diagrams(stripped)] == [BASE_ID, LOOSE_ID]
    assert tops.emitted_diagrams({}) == []


def test_textmate_omits_base_entries(models: ResolvedModels) -> None:
    text = json.dumps(json.loads(emit_textmate_json(models))).lower()
    assert "alpha" in text
    assert "gamma" not in text
    assert REMOVED not in text
    assert "kept" in text
    assert "tick" in text
