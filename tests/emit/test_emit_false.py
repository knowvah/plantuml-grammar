"""``emit: false`` entries are dropped by the TextMate emitter but still drive the interpreter."""

from __future__ import annotations

from pathlib import Path

from tools.emit.textmate import emit_textmate_json
from tools.interp import accepts
from tools.model.load import load_dir
from tools.model.resolve import resolve

HIDDEN = "zzzonly"
SHOWN = "alphaword"
MODEL = f"""schema_version: 1
id: toy
layer: diagram
diagram: CLASS
factory: ToyFactory
contexts:
  main:
    - {{command: Shown, provenance: {{class: t.Shown}}, kind: single,
       parts: {{literal: {SHOWN}, ci: false}}}}
    - {{command: Hidden, provenance: {{class: t.Hidden}}, kind: single, emit: false,
       parts: {{literal: {HIDDEN}, ci: false}}}}
"""


def test_emit_false_entry_is_only_visible_to_the_interpreter(tmp_path: Path) -> None:
    (tmp_path / "toy.yaml").write_text(MODEL, encoding="utf-8")
    models = resolve(load_dir(tmp_path))
    text = emit_textmate_json(models)
    assert SHOWN in text
    assert HIDDEN not in text
    block = f"@startuml\n{HIDDEN}\n@enduml"
    assert accepts(models, block)["accepted"] is True
