"""Tests for tools.interp.dispatch and rules/scan edge cases."""

from __future__ import annotations

import pytest
import regex

from tools.interp.dispatch import UML_TYPES, candidates, start_types
from tools.interp.scan import BlockTimeout, Deadline, scan_bracket, scan_multiline, unit_end
from tools.interp.source import Line, trin
from tools.model import ResolvedModel


def model(mid: str, diagram: str | None, layer: str = "diagram") -> ResolvedModel:
    return ResolvedModel(mid, layer, None, diagram, {}, {})


def body(*texts: str) -> list[Line]:
    return [Line(n, t, trin(t)) for n, t in enumerate(texts, start=1)]


def test_start_types_mirror_find_start_types() -> None:
    assert start_types("uml") == UML_TYPES
    assert start_types("umlfoo") == UML_TYPES
    assert start_types("project") == frozenset({"GANTT"})
    assert start_types("mindmap") == frozenset({"MINDMAP"})
    assert start_types("zzz") == frozenset()


def test_candidates_filter_by_type_and_sort_by_factory_order() -> None:
    models = {
        "state": model("state", "STATE"),
        "seq": model("seq", "SEQUENCE"),
        "mind": model("mind", "MINDMAP"),
        "shared": model("shared", None, layer="shared"),
        "cls": model("cls", "CLASS"),
    }
    assert [m.id for m in candidates(models, "uml", None)] == ["seq", "cls", "state"]
    assert [m.id for m in candidates(models, "mindmap", None)] == ["mind"]
    assert [m.id for m in candidates(models, None, None)] == ["state", "seq", "mind", "cls"]
    assert candidates(models, "zzz", None) == []


def test_start_map_skips_unknown_ids() -> None:
    models = {"seq": model("seq", "SEQUENCE")}
    assert [m.id for m in candidates(models, "uml", {"uml": ["ghost", "seq"]})] == ["seq"]


def test_unit_end_groups_nested_embedded_diagrams() -> None:
    src = body("{{", "{{salt", "}}", "}}", "x")
    assert unit_end(src, 0) == 4
    assert unit_end(src, 4) == 5
    assert unit_end(body("{{", "a"), 0) == 2  # unterminated: swallows the rest


def test_scan_multiline_requires_more_than_one_line() -> None:
    end = regex.compile("end", regex.I)
    deadline = Deadline(10.0)
    # The start line itself never closes the command (CommandMultilines2.java:102).
    assert scan_multiline(end, body("end", "x"), 0, deadline) is None
    assert scan_multiline(end, body("a", "end", "tail"), 0, deadline) == 2


def test_scan_bracket_single_line_is_partial() -> None:
    assert scan_bracket(body("package a {"), 0) is None
    assert scan_bracket(body("package a {", "}"), 0) == 2


def test_deadline_rejects_non_positive_budget() -> None:
    with pytest.raises(BlockTimeout):
        Deadline(0.0).fullmatch(regex.compile("a"), "a")


def test_scan_bracket_negative_depth_inside_one_unit_is_dropped() -> None:
    src = body("package a {", "{{", "}", "}", "}}")
    assert scan_bracket(src, 0) is None
