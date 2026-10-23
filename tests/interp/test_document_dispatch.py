"""Dispatch driven by the document layer's ``start_map`` and diagram ``factory``."""

from __future__ import annotations

from typing import Any

from tools.interp import accepts
from tools.interp.dispatch import Dispatcher, candidates, lookup
from tools.model import ResolvedModel, ResolvedModels

from .helpers import failure_of, uml

ANY = {"command": "Any", "provenance": {"class": "toy.Any"}, "kind": "opaque"}
END_LINE = {"regex": "[@\\\\]end.*"}
CLS_CONTEXTS = {
    "main": [
        {
            "command": "C",
            "provenance": {"class": "t"},
            "kind": "single",
            "parts": {"regex": r"cls\b.*"},
        }
    ]
}


def rule(name: str, regex: str, **extra: Any) -> dict[str, Any]:
    entry = {"command": name, "provenance": {"class": f"toy.{name}"}, "kind": "single"}
    return {**entry, "parts": {"regex": regex}, **extra}


def diagram(mid: str, factory: str, diagram_type: str, **kw: Any) -> ResolvedModel:
    contexts = kw.pop("contexts", {"main": [rule("C" + mid, mid + r"\b.*")]})
    return ResolvedModel(mid, "diagram", None, diagram_type, {}, contexts, factory=factory, **kw)


def document(start_map: dict[str, list[str]]) -> ResolvedModel:
    return ResolvedModel("doc", "document", None, None, {}, {}, start_map=start_map)


def family() -> ResolvedModels:
    models = [
        document({"uml": ["SeqF", "ClassF", "ActF", "ActF3"], "mindmap": ["MindF"]}),
        diagram("seq", "SeqF", "SEQUENCE"),
        diagram("cls", "ClassF", "CLASS"),
        diagram("clsfamily", "ClassF", "CLASS", includes=("cls",), contexts=CLS_CONTEXTS),
        diagram("act", "ActF", "ACTIVITY"),
        diagram("act3", "ActF3", "ACTIVITY"),
        diagram("mind", "MindF", "MINDMAP"),
    ]
    return {m.id: m for m in models}


def ids(found: list[ResolvedModel]) -> list[str]:
    return [m.id for m in found]


def test_lookup_is_exact_then_start_prefixed_then_find_start_types_prefix() -> None:
    table = {"uml": ["A"], "@startdot": ["B"], "def": ["C"]}
    assert lookup(table, "uml") == ["A"]
    assert lookup(table, "dot") == ["B"]
    assert lookup(table, "umlfoo") == ["A"]
    assert lookup(table, "definition") == ["C"]
    assert lookup(table, "zzz") is None
    assert lookup(table, "") is None


def test_document_start_map_picks_top_model_per_factory_in_map_order() -> None:
    models = family()
    assert ids(candidates(models, "uml", None)) == ["seq", "clsfamily", "act", "act3"]
    assert ids(candidates(models, "umlish", None)) == ["seq", "clsfamily", "act", "act3"]
    assert ids(candidates(models, "mindmap", None)) == ["mind"]
    assert Dispatcher(models).plan("zzz") is None
    assert candidates(models, "zzz", None) == []


def test_explicit_start_map_accepts_factories_and_model_ids() -> None:
    models = family()
    assert ids(candidates(models, "uml", {"uml": ["ClassF", "seq", "ghost"]})) == [
        "clsfamily",
        "seq",
    ]
    assert ids(candidates(models, "uml", {"uml": ["doc"]})) == []


def test_verdict_reports_diagram_type_and_top_model_id() -> None:
    models = family()
    verdict = accepts(models, uml("cls x"))
    assert (verdict["diagram"], verdict["model"]) == ("CLASS", "clsfamily")
    act3 = accepts(models, uml("act3 y"))
    assert (act3["diagram"], act3["model"]) == ("ACTIVITY", "act3")


def test_unknown_keyword_with_document_map_is_unsupported() -> None:
    verdict = accepts(family(), "@startfoo\nseq\n@endfoo")
    assert (verdict["accepted"], verdict["diagram"], verdict["model"]) == (True, None, None)


def test_without_document_model_falls_back_to_diagram_types() -> None:
    models = {k: v for k, v in family().items() if k != "doc"}
    assert ids(candidates(models, "mindmap", None)) == ["mind"]


def empty_models(**contexts: list[dict[str, Any]]) -> ResolvedModels:
    model = diagram("e", "EF", "SEQUENCE", contexts={"main": [], **contexts})
    return {"doc": document({"uml": ["EF"]}), "e": model}


def test_empty_context_opts_a_model_into_accepting_an_empty_body() -> None:
    models = empty_models(empty=[{**ANY, "parts": {"regex": ".*"}}])
    assert accepts(models, uml())["model"] == "e"
    assert accepts(models, uml("", "' comment"))["accepted"] is True
    assert failure_of(accepts(models, uml("x"))) == (2, "x")


def test_empty_context_sees_blank_lines_then_the_end_line() -> None:
    welcome = [rule("Blank", "", set="dead"), rule("Welcome", END_LINE["regex"])]
    models = empty_models(empty=welcome, dead=[])
    assert accepts(models, uml())["accepted"] is True
    assert failure_of(accepts(models, uml(""))) == (3, "@enduml")
    # A bare body has no end line: nothing for the end rule to match.
    assert accepts(models, "")["accepted"] is True


def test_without_empty_context_an_empty_body_is_rejected_at_the_start() -> None:
    models = empty_models()
    assert failure_of(accepts(models, uml())) == (1, "@startuml")
