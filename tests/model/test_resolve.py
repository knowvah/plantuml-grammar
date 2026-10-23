"""Tests for tools.model.resolve."""

from __future__ import annotations

from typing import Any

import pytest

from tools.model import Model, ModelError
from tools.model.load import load_dir
from tools.model.resolve import resolve, top_models

from .test_load import FIXTURES


def entry(parts: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"command": "C", "provenance": {"class": "X"}, "kind": "single", "parts": parts, **extra}


def model(mid: str, **kw: Any) -> Model:
    return Model(id=mid, layer="shared", **kw)


def contains_key(obj: Any, keys: set[str]) -> bool:
    if isinstance(obj, dict):
        return any(k in keys or contains_key(v, keys) for k, v in obj.items())
    if isinstance(obj, list):
        return any(contains_key(v, keys) for v in obj)
    return False


def test_a_includes_b_refs_var_in_c_fully_inlined() -> None:
    resolved = resolve(load_dir(FIXTURES))
    a = resolved["a"]
    assert not contains_key(a.contexts, {"include", "ref"})
    assert not contains_key(a.variables, {"include", "ref"})
    commands = [e["command"] for e in a.contexts["main"]]
    assert commands == ["CommandPaint", "CommandCreateClass"]
    paint = a.contexts["main"][0]["parts"]
    assert paint == {"seq": [{"literal": "color", "ci": True}, {"regex": "#\\w+"}]}
    create = a.contexts["main"][1]
    assert create["parts"]["seq"][2] == {"alt": [{"regex": "#\\w+"}, {"literal": "{", "ci": False}]}
    assert create["push"] == "body"
    assert create["end"] == {"literal": "}", "ci": False}


def test_resolved_merges_included_contexts_and_variables() -> None:
    a = resolve(load_dir(FIXTURES))["a"]
    assert sorted(a.contexts) == ["body", "common", "main"]
    assert sorted(a.variables) == ["COLOR", "PAINTED", "SPACE"]
    assert a.diagram == "CLASS"


def test_own_definitions_override_included() -> None:
    c = model("c", variables={"V": {"regex": "c"}})
    a = model("a", include=["c"], variables={"V": {"regex": "a"}})
    assert resolve({"a": a, "c": c})["a"].variables["V"] == {"regex": "a"}


def test_model_include_cycle_names_path() -> None:
    models = {"A": model("A", include=["B"]), "B": model("B", include=["A"])}
    with pytest.raises(ModelError, match="include cycle: A → B → A"):
        resolve(models)


def test_self_include_cycle() -> None:
    with pytest.raises(ModelError, match="include cycle: A → A"):
        resolve({"A": model("A", include=["A"])})


def test_context_include_cycle_across_models() -> None:
    a = model("A", contexts={"main": [{"include": "B"}]})
    b = model("B", contexts={"main": [{"include": "A"}]})
    with pytest.raises(ModelError, match=r"include cycle: A\.main → B\.main → A\.main"):
        resolve({"A": a, "B": b})


def test_variable_cycle() -> None:
    a = model("A", variables={"X": {"ref": "Y"}, "Y": {"ref": "X"}})
    with pytest.raises(ModelError, match=r"variable cycle: A\.X → A\.Y → A\.X"):
        resolve({"A": a})


def test_local_context_wins_over_model_id_and_hash_form() -> None:
    other = model("other", contexts={"main": [entry({"regex": "o"})]})
    a = model(
        "a",
        contexts={
            "other": [entry({"regex": "local"})],
            "main": [{"include": "other"}, {"include": "other#main"}],
        },
    )
    parts = [e["parts"] for e in resolve({"a": a, "other": other})["a"].contexts["main"]]
    assert parts == [{"regex": "local"}, {"regex": "o"}]


def test_unknown_include_and_push_targets() -> None:
    bad_inc = model("a", contexts={"main": [{"include": "nope"}]})
    with pytest.raises(ModelError, match="include target 'nope' not found") as info:
        resolve({"a": bad_inc})
    assert info.value.pointer == "/contexts/main/0/include"
    bad_push = model("a", contexts={"main": [entry({"regex": "x"}, push="ghost")]})
    with pytest.raises(ModelError, match="unknown context 'ghost'"):
        resolve({"a": bad_push})
    bad_hash = model("a", contexts={"main": [{"include": "zzz#main"}]})
    with pytest.raises(ModelError, match="not found"):
        resolve({"a": bad_hash})


def test_diamond_include_is_not_a_cycle() -> None:
    d = model("d", variables={"V": {"regex": "d"}})
    b = model("b", include=["d"])
    c = model("c", include=["d"])
    a = model("a", include=["b", "c"], contexts={"main": [entry({"ref": "V"})]})
    out = resolve({"a": a, "b": b, "c": c, "d": d})
    assert out["a"].contexts["main"][0]["parts"] == {"regex": "d"}


def diagram(mid: str, factory: str, **kw: Any) -> Model:
    return Model(id=mid, layer="diagram", diagram="CLASS", factory=factory, **kw)


def test_factory_start_map_and_transitive_includes_are_copied() -> None:
    doc = Model(id="doc", layer="document", start_map={"uml": ["F"]})
    base = diagram("base", "F")
    mid = model("mid", include=["base"])
    top = diagram("top", "F", include=["mid"])
    out = resolve({"doc": doc, "base": base, "mid": mid, "top": top})
    assert out["doc"].start_map == {"uml": ["F"]}
    assert out["doc"].factory is None
    assert out["top"].factory == "F"
    assert out["top"].includes == ("mid", "base")
    assert out["base"].includes == ()


def test_top_models_picks_the_transitively_including_model() -> None:
    base = diagram("base", "F")
    mid = model("mid", include=["base"])
    top = diagram("top", "F", include=["mid"])
    other = diagram("other", "G")
    out = resolve({"base": base, "mid": mid, "top": top, "other": other})
    assert top_models(out) == {"F": "top", "G": "other"}


def test_two_top_models_for_one_factory_is_an_error_naming_both() -> None:
    a = diagram("ActivityA", "ActivityDiagramFactory")
    b = diagram("ActivityB", "ActivityDiagramFactory")
    with pytest.raises(
        ModelError, match="two top models for factory 'ActivityDiagramFactory'"
    ) as info:
        resolve({"ActivityA": a, "ActivityB": b})
    assert "'ActivityA'" in str(info.value)
    assert "'ActivityB'" in str(info.value)
    assert info.value.pointer == "/factory"


def test_distinct_factories_sharing_a_diagram_type_are_both_tops() -> None:
    a = diagram("act", "ActivityDiagramFactory")
    b = diagram("act3", "ActivityDiagramFactory3")
    out = resolve({"act": a, "act3": b})
    assert top_models(out) == {"ActivityDiagramFactory": "act", "ActivityDiagramFactory3": "act3"}
