"""Tests for tools.model.patch (overrides, insert_before, insert_after)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

from tools.model import Model, ModelError, ModelLoadError
from tools.model.load import load_dir
from tools.model.patch import matches, merge_override, simple_class_name
from tools.model.resolve import resolve

FQCN = "net.sourceforge.plantuml.classdiagram.command.CommandCreateClass"


def ent(command: str, regex: str = "x", cls: str = FQCN, **extra: Any) -> dict[str, Any]:
    return {
        "command": command,
        "provenance": {"class": cls},
        "kind": "single",
        "parts": {"regex": regex},
        **extra,
    }


def base(**kw: Any) -> Model:
    contexts = {
        "main": [ent("A", "a"), ent("B", "b", cls="p.Outer$Inner"), ent("A_2", "a2", cls=FQCN)],
        "other": [ent("C", "c")],
    }
    return Model(id="base", layer="diagram", diagram="CLASS", contexts=contexts, **kw)


def top(**kw: Any) -> Model:
    return Model(id="top", layer="diagram", diagram="CLASS", include=["base"], **kw)


def shared(**kw: Any) -> Model:
    return Model(id="common", layer="shared", **kw)


def cmds(models: dict[str, Model], mid: str = "top", ctx: str = "main") -> list[str]:
    return [e["command"] for e in resolve(models)[mid].contexts[ctx]]


def err(models: dict[str, Model]) -> ModelError:
    with pytest.raises(ModelError) as info:
        resolve(models)
    return info.value


def test_class_name_helpers() -> None:
    assert simple_class_name(ent("B", cls="p.Outer$Inner")) == "Outer_Inner"
    assert matches(ent("A"), "A")
    assert matches(ent("A"), "CommandCreateClass")
    assert not matches(ent("A"), "Other")


def test_merge_override_shallow_and_null_deletes() -> None:
    merged = merge_override(
        ent("A", push="p", end={"regex": "e"}), {"push": None, "kind": "multiline"}
    )
    assert "push" not in merged
    assert merged["kind"] == "multiline" and merged["end"] == {"regex": "e"}


def test_override_by_command_id_adds_push_and_marks_refined_by() -> None:
    models = {"base": base(), "top": top(overrides={"A": {"push": "other"}})}
    main = resolve(models)["top"].contexts["main"]
    assert main[0]["push"] == "other" and main[0]["refined_by"] == "top"
    assert main[0]["parts"] == {"regex": "a"} and main[0]["command"] == "A"
    assert "push" not in main[1] and "refined_by" not in main[1]
    assert "refined_by" not in resolve(models)["base"].contexts["main"][0]


def test_override_by_class_name_hits_every_repeat() -> None:
    models = {"base": base(), "top": top(overrides={"CommandCreateClass": {"push": "other"}})}
    main = resolve(models)["top"].contexts["main"]
    assert [e.get("push") for e in main] == ["other", None, "other"]


def test_override_dollar_class_name_and_all_contexts() -> None:
    models = {
        "base": base(),
        "top": top(overrides={"Outer_Inner": {"kind": "opaque"}, "C": {"pop": True}}),
    }
    out = resolve(models)["top"]
    assert out.contexts["main"][1]["kind"] == "opaque"
    assert out.contexts["other"][0]["pop"] is True


def test_override_replaces_parts_and_expands_refs_in_declaring_scope() -> None:
    top_model = top(
        variables={"V": {"regex": "v"}}, overrides={"A": {"parts": {"seq": [{"ref": "V"}]}}}
    )
    main = resolve({"base": base(), "top": top_model})["top"].contexts["main"]
    assert main[0]["parts"] == {"seq": [{"regex": "v"}]}


def test_single_to_multiline_with_end_and_null_removal() -> None:
    patch = {"kind": "multiline", "end": {"regex": "\\}"}, "push": "other"}
    models = {"base": base(), "top": top(overrides={"A": patch, "B": {"push": None}})}
    main = resolve(models)["top"].contexts["main"]
    assert main[0]["kind"] == "multiline" and main[0]["end"] == {"regex": "\\}"}


def test_null_pop_deletes_key_so_push_can_be_added() -> None:
    contexts = {"main": [ent("A", pop=True)], "other": [ent("C")]}
    b = Model(id="base", layer="diagram", diagram="CLASS", contexts=contexts)
    t = top(overrides={"A": {"pop": None, "push": "other"}})
    entry = resolve({"base": b, "top": t})["top"].contexts["main"][0]
    assert "pop" not in entry and entry["push"] == "other"


def test_mutual_exclusion_after_merge_is_error() -> None:
    contexts = {"main": [ent("A", pop=True)], "other": [ent("C")]}
    b = Model(id="base", layer="diagram", diagram="CLASS", contexts=contexts)
    e = err({"base": b, "top": top(overrides={"A": {"push": "other"}})})
    assert "invalid entry for 'A'" in e.message
    assert e.pointer == "/overrides/A"


def test_multiline_without_end_is_invalid_after_merge() -> None:
    e = err({"base": base(), "top": top(overrides={"A": {"kind": "multiline"}})})
    assert "invalid entry" in e.message


def test_unknown_push_target_in_override_names_pointer() -> None:
    e = err({"base": base(), "top": top(overrides={"A": {"push": "ghost"}})})
    assert e.message == "unknown context 'ghost'" and e.pointer == "/overrides/A/push"


def test_remove_drops_entry_keeping_order() -> None:
    models = {"base": base(), "top": top(overrides={"B": {"remove": True}})}
    assert cmds(models) == ["A", "A_2"]


def test_unmatched_key_in_diagram_is_error_for_each_section() -> None:
    for section, value in (
        ("overrides", {"Nope": {"push": "other"}}),
        ("insert_before", {"Nope": [ent("N")]}),
        ("insert_after", {"Nope": [ent("N")]}),
    ):
        e = err({"base": base(), "top": top(**{section: value})})
        assert e.message == f"{section} key 'Nope' matches no entry"
        assert e.pointer == f"/{section}/Nope"


def test_insert_before_and_after_relative_position() -> None:
    models = {
        "base": base(),
        "top": top(insert_before={"B": [ent("X"), ent("Y")]}, insert_after={"A": [ent("Z")]}),
    }
    assert cmds(models) == ["A", "Z", "X", "Y", "B", "A_2"]


def test_insert_class_name_key_inserts_at_each_repeat() -> None:
    models = {"base": base(), "top": top(insert_after={"CommandCreateClass": [ent("N")]})}
    assert cmds(models) == ["A", "N", "B", "A_2", "N"]


def test_inserted_entries_resolve_refs_in_declaring_scope_and_are_not_re_patched() -> None:
    t = top(
        variables={"V": {"regex": "v"}},
        insert_before={"A": [ent("X", "unused") | {"parts": {"ref": "V"}}]},
        overrides={"X": {"push": "other"}, "A": {"kind": "opaque"}},
    )
    models = {"base": base(), "top": t}
    with pytest.raises(ModelError, match="overrides key 'X' matches no entry"):
        resolve(models)
    t2 = top(
        variables={"V": {"regex": "v"}},
        insert_before={"A": [ent("X") | {"parts": {"ref": "V"}}]},
    )
    first = resolve({"base": base(), "top": t2})["top"].contexts["main"][0]
    assert first["command"] == "X" and first["parts"] == {"regex": "v"}


def test_insert_unknown_push_target_is_error() -> None:
    e = err({"base": base(), "top": top(insert_after={"A": [ent("N", push="ghost")]})})
    assert e.pointer == "/insert_after/A/0/push"


def test_insert_relative_to_removed_entry_is_error() -> None:
    t = top(overrides={"A": {"remove": True}}, insert_after={"A": [ent("N")]})
    e = err({"base": base(), "top": t})
    assert "insert relative to removed entry 'A'" in e.message
    assert e.pointer == "/insert_after/A"


def test_shared_overrides_apply_to_including_diagram_and_may_match_nothing() -> None:
    common = shared(
        overrides={"A": {"kind": "opaque"}, "AbsentCommand": {"push": "other"}},
        insert_after={"Missing": [ent("M")]},
        contexts={"main": [ent("S", cls="p.Shared")]},
    )
    t = Model(id="top", layer="diagram", diagram="CLASS", include=["base", "common"])
    out = resolve({"base": base(), "common": common, "top": t})
    assert out["top"].contexts["main"][0]["kind"] == "opaque"
    assert out["top"].contexts["main"][0]["refined_by"] == "common"
    assert out["common"].contexts["main"][0].get("refined_by") is None


def test_shared_models_own_patches_do_not_apply_to_itself() -> None:
    common = shared(contexts={"main": [ent("S")]}, overrides={"S": {"kind": "opaque"}})
    assert resolve({"common": common})["common"].contexts["main"][0]["kind"] == "single"


def test_model_keys_win_over_included_without_merging() -> None:
    common = shared(overrides={"A": {"kind": "opaque", "push": "other"}})
    t = Model(
        id="top",
        layer="diagram",
        diagram="CLASS",
        include=["base", "common"],
        overrides={"A": {"push": "other"}},
    )
    entry = resolve({"base": base(), "common": common, "top": t})["top"].contexts["main"][0]
    assert entry["kind"] == "single" and entry["push"] == "other"
    assert entry["refined_by"] == "top"


def test_model_key_wins_over_included_key_hitting_the_same_entry() -> None:
    # different keys (a class name in common, a command id in top) both hit A_2
    common = shared(overrides={"CommandCreateClass": {"kind": "opaque", "push": "other"}})
    t = Model(
        id="top",
        layer="diagram",
        diagram="CLASS",
        include=["base", "common"],
        overrides={"A_2": {"kind": "multiline", "end": {"regex": "e"}}},
    )
    main = resolve({"base": base(), "common": common, "top": t})["top"].contexts["main"]
    assert main[2]["kind"] == "multiline" and main[2]["push"] == "other"
    assert main[2]["refined_by"] == "top"
    assert main[0]["kind"] == "opaque" and main[0]["refined_by"] == "common"


def test_unmatched_key_from_included_diagram_model_is_error() -> None:
    mid = Model(
        id="mid",
        layer="diagram",
        diagram="CLASS",
        include=["base"],
        overrides={"A": {"kind": "opaque"}},
    )
    t = Model(id="top", layer="diagram", diagram="CLASS", include=["mid"])
    out = resolve({"base": base(), "mid": mid, "top": t})
    assert out["top"].contexts["main"][0]["kind"] == "opaque"
    other = Model(id="other", layer="diagram", diagram="CLASS", contexts={"main": [ent("Q")]})
    bad = Model(id="bad", layer="diagram", diagram="CLASS", include=["other", "mid"])
    e = err({"base": base(), "mid": mid, "other": other, "bad": bad})
    assert e.message == "overrides key 'A' matches no entry"


def test_includes_in_context_are_spliced_before_patching() -> None:
    spliced = Model(
        id="spl",
        layer="diagram",
        diagram="CLASS",
        include=["base"],
        contexts={"main": [{"include": "base#main"}, ent("Own")]},
        overrides={"Own": {"kind": "opaque"}, "B": {"remove": True}},
    )
    assert cmds({"base": base(), "spl": spliced}, "spl") == ["A", "A_2", "Own"]


def write(tmp_path: Path, name: str, body: str) -> None:
    (tmp_path / name).write_text(textwrap.dedent(body), encoding="utf-8")


BASE_YAML = """\
    schema_version: 1
    id: base
    layer: diagram
    diagram: CLASS
    factory: BaseFactory
    contexts:
      main:
        - command: CommandA
          provenance: {class: p.CommandA}
          kind: single
          parts: {regex: "a"}
"""


def load_errors(tmp_path: Path) -> list[str]:
    with pytest.raises(ModelLoadError) as info:
        load_dir(tmp_path)
    return [str(e) for e in info.value.errors]


def test_load_yaml_roundtrip_with_overrides_and_inserts(tmp_path: Path) -> None:
    write(tmp_path, "base.yaml", BASE_YAML)
    write(
        tmp_path,
        "top.yaml",
        """\
        schema_version: 1
        id: top
        layer: diagram
        diagram: CLASS
        factory: BaseFactory
        include: [base]
        overrides:
          CommandA: {push: body, pop: null}
        insert_before:
          CommandA:
            - {command: Pre, provenance: {class: x.Pre}, kind: single, parts: {regex: "p"}}
        contexts:
          body:
            - {command: Close, provenance: {class: x.Close}, kind: single,
               parts: {regex: "\\\\}"}, pop: true}
        """,
    )
    models = load_dir(tmp_path)
    assert models["top"].overrides == {"CommandA": {"push": "body", "pop": None}}
    main = resolve(models)["top"].contexts["main"]
    assert [e["command"] for e in main] == ["Pre", "CommandA"]
    assert main[1]["push"] == "body"


def test_schema_rejects_patch_keys_on_document_layer(tmp_path: Path) -> None:
    write(
        tmp_path,
        "d.yaml",
        "schema_version: 1\nid: d\nlayer: document\noverrides:\n  A: {push: x}\n",
    )
    assert load_errors(tmp_path)


def test_schema_rejects_remove_with_other_keys_and_bad_patch(tmp_path: Path) -> None:
    write(
        tmp_path,
        "s.yaml",
        "schema_version: 1\nid: s\nlayer: shared\noverrides:\n  A: {remove: true, push: x}\n"
        "  B: {unknown: 1}\n  C: {}\n",
    )
    errors = load_errors(tmp_path)
    assert any("/overrides/A" in e for e in errors)
    assert any("/overrides/B/unknown" in e for e in errors)
    assert any("/overrides/C" in e for e in errors)


def test_schema_rejects_refined_by_in_patch_and_empty_insert_list(tmp_path: Path) -> None:
    write(
        tmp_path,
        "s.yaml",
        "schema_version: 1\nid: s\nlayer: shared\noverrides:\n  A: {refined_by: x}\n"
        "insert_after:\n  B: []\n",
    )
    errors = load_errors(tmp_path)
    assert any("/overrides/A/refined_by" in e for e in errors)
    assert any("/insert_after/B" in e for e in errors)


def test_loader_checks_regexes_in_patches(tmp_path: Path) -> None:
    write(
        tmp_path,
        "s.yaml",
        """\
        schema_version: 1
        id: s
        layer: shared
        overrides:
          A: {parts: {regex: "(unclosed"}, end: {regex: "%s"}, push: null}
        insert_after:
          B:
            - {command: N, provenance: {class: x.N}, kind: single, parts: {regex: "["}}
        """,
    )
    errors = load_errors(tmp_path)
    assert any("/overrides/A/parts/regex" in e and "does not compile" in e for e in errors)
    assert any("/overrides/A/end/regex" in e and "macro" in e for e in errors)
    assert any("/insert_after/B/0/parts/regex" in e for e in errors)
