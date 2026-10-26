"""The engine JSON (C1): shape, determinism, dedup, glue flag, unsupported mapping."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.emit.engine_support import (
    PIN,
    REPO,
    engine_entries,
    entry,
    lit,
    rx,
    synthetic,
)
from tools.emit import engine as eng
from tools.emit.build import EMITTERS, build
from tools.interp.factories import NON_COMMAND_FACTORIES
from tools.model import ResolvedModel
from tools.model.java_regex_js import line_pattern_js
from tools.model.js_prefix import prefix_pattern
from tools.model.resolve import top_models

UNSUPPORTED_REGEX = r"(a)(?>b)\1"
ENGINE_KEYS = {"engine_format", "pin", "patterns", "context_table", "models", "model_order", "tops"}
MODEL_KEYS = {
    "layer",
    "diagram",
    "factory",
    "glue_units",
    "empty_needs_end",
    "start_map",
    "includes",
    "contexts",
}
ENTRY_REQUIRED = {
    "command",
    "kind",
    "start",
    "action",
    "target",
    "require_pop",
    "reject",
    "gives",
    "needs",
    "untrimmed",
}
ENTRY_OPTIONAL = {"end", "join"}


pytest_plugins = ["tests.emit.engine_support"]


# --- shape ---------------------------------------------------------------------------------


def test_top_level_shape(built, resolved):
    assert set(built) == ENGINE_KEYS
    assert built["engine_format"] == 1
    assert built["pin"] == PIN
    assert built["model_order"] == list(resolved)
    assert set(built["models"]) == set(resolved)
    assert built["tops"] == top_models(resolved)


def test_model_and_entry_shape(built, resolved):
    for mid, model in built["models"].items():
        assert set(model) == MODEL_KEYS, mid
        assert model["layer"] == resolved[mid].layer
        assert model["includes"] == list(resolved[mid].includes)
        assert model["start_map"] == resolved[mid].start_map
    count = len(built["patterns"])
    for entries in built["context_table"]:
        for e in entries:
            assert ENTRY_REQUIRED <= set(e) <= ENTRY_REQUIRED | ENTRY_OPTIONAL
            assert 0 <= e["start"] < count


def test_context_indices_point_into_the_table(built):
    size = len(built["context_table"])
    indices = [i for m in built["models"].values() for i in m["contexts"].values()]
    assert indices and all(0 <= i < size for i in indices)


def test_pin_is_read_from_upstream_pin_json(resolved):
    pin = json.loads((REPO / "upstream-pin.json").read_text())["sha"]
    assert eng.read_pin() == pin
    assert json.loads(eng.emit_engine_json(synthetic([entry(lit("a"))])))["pin"] == pin


def test_engine_emitter_is_registered_with_a_post_write_check():
    spec = EMITTERS["engine"]
    assert (spec.filename, spec.check) == (
        "plantuml.engine.json",
        "tools.emit.engine:report_engine",
    )


def test_every_entry_maps_to_the_line_pattern_of_its_parts(resolved, built):
    for mid, name, index, source in engine_entries(resolved, built):
        pid = built["context_table"][built["models"][mid]["contexts"][name]][index]["start"]
        pattern = built["patterns"][pid]
        if "source" in pattern:
            expected = line_pattern_js(eng.part_to_js(source["parts"]))
            assert (pattern["source"], pattern["flags"]) == (expected, "u")
            assert set(pattern) <= {"source", "flags", "guard"}


def test_end_join_and_action_fields(resolved, built):
    seen = {"end": 0, "join": 0, "push": 0, "pop": 0, "set": 0, "untrimmed": 0}
    for mid, name, index, source in engine_entries(resolved, built):
        out = built["context_table"][built["models"][mid]["contexts"][name]][index]
        assert out["command"] == source["command"]
        assert out["kind"] == source["kind"]
        if source.get("end") is not None:
            seen["end"] += 1
            assert built["patterns"][out["end"]].keys() <= {"source", "flags", "split", "any"}
        if "join" in source:
            seen["join"] += 1
            assert out["join"]["max_lines"] == source["join"]["max_lines"]
            prefix = built["patterns"][out["join"]["prefix"]]
            assert prefix["source"] == prefix_pattern(source["parts"], source["command"])
        for key in ("push", "set"):
            if key in source:
                seen[key] += 1
                assert (out["action"], out["target"]) == (key, source[key])
        if source.get("pop"):
            seen["pop"] += 1
            assert (out["action"], out["target"]) == ("pop", "")
        if source.get("trim") is False:
            seen["untrimmed"] += 1
            assert out["untrimmed"] is True
    assert all(count > 0 for count in seen.values()), seen


def test_synthetic_entry_fields_are_mapped():
    e = entry(
        lit("ab"),
        end=rx("x+"),
        join={"max_lines": 5},
        push="ctx",
        require_pop=True,
        reject=True,
        gives="g",
        needs="n",
        trim=False,
    )
    data = eng.build_engine(synthetic([e]), PIN)
    out = data["context_table"][0][0]
    assert out["action"] == "push" and out["target"] == "ctx"
    assert (out["require_pop"], out["reject"], out["untrimmed"]) == (True, True, True)
    assert (out["gives"], out["needs"]) == ("g", "n")
    assert out["join"]["max_lines"] == 5
    assert data["patterns"][out["start"]]["source"] == line_pattern_js("(?:ab)")
    assert data["patterns"][out["end"]]["source"] == line_pattern_js("(?:x+)")
    assert data["patterns"][out["join"]["prefix"]]["source"] == prefix_pattern(lit("ab"), "Cmd")


def test_null_end_is_omitted():
    data = eng.build_engine(synthetic([entry(lit("a"), end=None)]), PIN)
    assert "end" not in data["context_table"][0][0]


# --- determinism, dedup, glue ---------------------------------------------------------------


def test_render_is_deterministic_and_compact(resolved):
    first = eng.render_engine(resolved, PIN)
    assert first == eng.render_engine(resolved, PIN)
    assert first.endswith("}\n") and not first.endswith("\n\n")
    assert ", " not in first[:200] and ": " not in first[:200]
    assert json.loads(first)["pin"] == PIN


def test_keys_are_sorted_in_the_output(built):
    text = eng.render_engine(synthetic([entry(lit("a"))]), PIN)
    top_order = [m.group(1) for m in re.finditer(r'"(\w+)":', text) if m.group(1) in ENGINE_KEYS]
    assert top_order == sorted(ENGINE_KEYS)


def test_build_writes_identical_files_twice(tmp_path):
    model_dir = Path(__file__).parent / "fixtures" / "toy"
    first = build(["engine"], model_dir, tmp_path / "a")[0]
    second = build(["engine"], model_dir, tmp_path / "b")[0]
    assert first.read_bytes() == second.read_bytes()
    assert json.loads(first.read_text())["engine_format"] == 1


def test_patterns_and_contexts_are_deduplicated(built):
    keys = [json.dumps(p, sort_keys=True) for p in built["patterns"]]
    assert len(keys) == len(set(keys))
    tables = [json.dumps(c, sort_keys=True) for c in built["context_table"]]
    assert len(tables) == len(set(tables))


def test_equal_parts_share_one_pattern_and_equal_contexts_one_table_entry():
    models = synthetic([entry(lit("a")), entry(lit("a"), reject=True)])
    models["n"] = ResolvedModel(
        "n", "diagram", None, "Y", {}, {"main": models["m"].contexts["main"]}
    )
    data = eng.build_engine(models, PIN)
    starts = [e["start"] for e in data["context_table"][0]]
    assert starts[0] == starts[1]
    assert len(data["patterns"]) == 1
    assert data["models"]["m"]["contexts"] == data["models"]["n"]["contexts"] == {"main": 0}
    assert len(data["context_table"]) == 1


@pytest.mark.parametrize(
    ("factory", "glue"),
    [("SequenceDiagramFactory", True), ("JsonDiagramFactory", False), (None, True)],
)
def test_glue_units_follows_non_command_factories(factory, glue):
    data = eng.build_engine(synthetic([entry(lit("a"))], factory), PIN)
    assert data["models"]["m"]["glue_units"] is glue


def test_glue_units_for_every_model(built):
    for model in built["models"].values():
        assert model["glue_units"] is (model["factory"] not in NON_COMMAND_FACTORIES)


# --- unsupported ---------------------------------------------------------------------------


def test_untranslatable_regex_becomes_unsupported_with_a_reason():
    data = eng.build_engine(synthetic([entry(rx(UNSUPPORTED_REGEX))]), PIN)
    pattern = data["patterns"][data["context_table"][0][0]["start"]]
    assert pattern == {
        "unsupported": "atomic group or possessive quantifier with a numbered back reference"
    }


def test_oversized_expansion_becomes_unsupported(monkeypatch):
    def boom(source: str, depth: int | None = None) -> str:
        raise eng.Unsupported("expansion is over 262144 bytes")

    monkeypatch.setattr(eng, "expand_subroutines", boom)
    data = eng.build_engine(synthetic([entry(rx("a"))]), PIN)
    assert data["patterns"][0] == {"unsupported": "expansion is over 262144 bytes"}


def test_unresolved_part_is_a_build_error():
    with pytest.raises(eng.EngineBuildError, match="unresolved"):
        eng.build_engine(synthetic([entry({"ref": "X"})]), PIN)


def test_real_model_has_no_unsupported_pattern(built):
    assert [p for p in built["patterns"] if "unsupported" in p] == []


# --- atomic renumbering --------------------------------------------------------------------


def test_atomic_names_are_unique_across_a_composed_pattern():
    part = {"seq": [rx("(?>a+)b"), rx("(?>c+)d"), {"opt": rx("(?>e|f)")}]}
    body = eng.part_to_js(part)
    names = re.findall(r"\(\?<(_a\d+)>", body)
    assert names == ["_a0", "_a1", "_a2"]
    assert sorted(re.findall(r"\\k<(_a\d+)>", body)) == names
