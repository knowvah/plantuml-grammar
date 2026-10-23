"""``require_pop`` and ``reject`` entry keys, on toy models written to a temp dir."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tools.interp import accepts
from tools.interp.engine import Interpreter
from tools.model import ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve

from .helpers import failure_of, uml

HEADER = "schema_version: 1\nid: toy\nlayer: diagram\ndiagram: CLASS\n"
BODY = """
  body:
    - {command: Close, provenance: {class: t.Close}, kind: single, parts: {regex: '\\}'}, pop: true}
    - {command: Inner, provenance: {class: t.Inner}, kind: single, parts: {regex: 'inner \\{'},
       push: body, require_pop: true}
    - {command: Item, provenance: {class: t.Item}, kind: single, parts: {regex: '\\w+'}}
"""
OPEN = (
    "    - {command: Open, provenance: {class: t.Open}, kind: single, parts: {regex: 'open \\{'},"
    " push: body%s}\n"
)
PLAIN = (
    "    - {command: Plain, provenance: {class: t.Plain}, kind: single, parts: {regex: 'open.*'}}\n"
)
WORD = "    - {command: Word, provenance: {class: t.Word}, kind: single, parts: {regex: '\\w+'}}\n"
CATCH_ALL = "    - {command: Any, provenance: {class: t.Any}, kind: single, parts: {regex: '.+'}}\n"


def toy(tmp_path: Path, main: str) -> ResolvedModels:
    (tmp_path / "toy.yaml").write_text(
        HEADER + "contexts:\n  main:\n" + main + BODY, encoding="utf-8"
    )
    return resolve(load_dir(tmp_path))


def run(models: ResolvedModels, *lines: str) -> tuple[bool, tuple[int, str] | None]:
    verdict = accepts(models, uml(*lines))
    return verdict["accepted"], None if verdict["accepted"] else failure_of(verdict)


# --- require_pop ---------------------------------------------------------------------------


def test_unterminated_body_is_accepted_without_require_pop(tmp_path: Path) -> None:
    models = toy(tmp_path, WORD + OPEN % "")
    assert run(models, "open {", "a", "b") == (True, None)


def test_require_pop_rejects_unterminated_body_at_pushing_line(tmp_path: Path) -> None:
    models = toy(tmp_path, WORD + OPEN % ", require_pop: true")
    assert run(models, "ok", "open {", "a", "b") == (False, (3, "open {"))


def test_require_pop_accepts_terminated_body(tmp_path: Path) -> None:
    models = toy(tmp_path, WORD + OPEN % ", require_pop: true")
    assert run(models, "open {", "a", "}", "c") == (True, None)


def test_require_pop_rejects_when_body_ends_right_after_push(tmp_path: Path) -> None:
    models = toy(tmp_path, WORD + OPEN % ", require_pop: true")
    assert run(models, "open {") == (False, (2, "open {"))


def test_require_pop_backtracks_to_later_candidate_at_pushing_line(tmp_path: Path) -> None:
    # PSystemCommandFactory.getCandidate: a multiline command that never completes is
    # skipped (`continue`) and the next command is tried for the same start line.
    models = toy(tmp_path, WORD + OPEN % ", require_pop: true" + PLAIN)
    assert run(models, "open {", "a", "b") == (True, None)


def test_backtracking_resumes_in_the_context_of_the_pushing_line(tmp_path: Path) -> None:
    models = toy(tmp_path, WORD + OPEN % ", require_pop: true" + PLAIN)
    # The fallback consumes `open {`; `inner {` is then read in `main`, which lacks it.
    assert run(models, "open {", "inner {", "x", "}") == (False, (3, "inner {"))


def test_later_candidate_that_also_fails_reports_pushing_line(tmp_path: Path) -> None:
    other = (
        "    - {command: Nope, provenance: {class: t.Nope}, kind: single, parts: {regex: 'zzz'}}\n"
    )
    models = toy(tmp_path, WORD + OPEN % ", require_pop: true" + other)
    assert run(models, "open {", "a") == (False, (2, "open {"))


def test_nested_require_pop_with_unclosed_outer_backtracks_to_outer_line(tmp_path: Path) -> None:
    models = toy(tmp_path, WORD + OPEN % ", require_pop: true")
    # inner is closed, outer is not: the outermost open frame decides.
    assert run(models, "open {", "inner {", "x", "}") == (False, (2, "open {"))
    assert run(models, "open {", "inner {", "x", "}", "}") == (True, None)


def test_inner_unclosed_frame_fails_at_the_outermost_open_line(tmp_path: Path) -> None:
    models = toy(tmp_path, WORD + OPEN % ", require_pop: true")
    assert run(models, "open {", "inner {", "x") == (False, (2, "open {"))


def test_closed_frames_do_not_backtrack(tmp_path: Path) -> None:
    models = toy(tmp_path, WORD + OPEN % ", require_pop: true")
    assert run(models, "open {", "}", "open {", "a") == (False, (4, "open {"))


def test_pop_on_bottom_context_keeps_frames_aligned(tmp_path: Path) -> None:
    bottom_pop = (
        "    - {command: P, provenance: {class: t.P}, kind: single, parts: {regex: p}, pop: true}\n"
    )
    main = bottom_pop + WORD + OPEN % ", require_pop: true"
    models = toy(tmp_path, main)
    assert run(models, "p", "open {", "}") == (True, None)
    assert run(models, "p", "open {") == (False, (3, "open {"))


def test_set_keeps_the_open_frame_marker(tmp_path: Path) -> None:
    body = """
  body:
    - {command: Sw, provenance: {class: t.Sw}, kind: single, parts: {regex: sw}, set: other}
  other:
    - {command: Close, provenance: {class: t.Close}, kind: single, parts: {regex: '\\}'}, pop: true}
"""
    text = HEADER + "contexts:\n  main:\n" + WORD + OPEN % ", require_pop: true" + body
    (tmp_path / "toy.yaml").write_text(text, encoding="utf-8")
    models = resolve(load_dir(tmp_path))
    assert run(models, "open {", "sw", "}") == (True, None)
    assert run(models, "open {", "sw") == (False, (2, "open {"))


# --- reject --------------------------------------------------------------------------------

REJECT = (
    "    - {command: Zero, provenance: {class: t.Zero}, kind: single,"
    " parts: {regex: 'page 0'}, reject: true}\n"
)
PAGE = (
    "    - {command: Page, provenance: {class: t.Page}, kind: single,"
    " parts: {regex: 'page \\d+'}}\n"
)


def test_without_reject_a_catch_all_swallows_the_line(tmp_path: Path) -> None:
    models = toy(tmp_path, PAGE + CATCH_ALL)
    assert run(models, "page 0") == (True, None)


def test_reject_stops_fall_through_to_a_later_catch_all(tmp_path: Path) -> None:
    models = toy(tmp_path, REJECT + PAGE + CATCH_ALL)
    assert run(models, "x", "page 0") == (False, (3, "page 0"))


def test_reject_leaves_other_lines_to_later_entries(tmp_path: Path) -> None:
    models = toy(tmp_path, REJECT + PAGE + CATCH_ALL)
    assert run(models, "page 3", "anything") == (True, None)


def test_reject_only_applies_when_selected_first(tmp_path: Path) -> None:
    models = toy(tmp_path, PAGE.replace("\\d+", "0") + REJECT)
    assert run(models, "page 0") == (True, None)


def test_reject_inside_pushed_context(tmp_path: Path) -> None:
    body = """
  body:
    - {command: Close, provenance: {class: t.Close}, kind: single, parts: {regex: '\\}'}, pop: true}
    - {command: Bad, provenance: {class: t.Bad}, kind: single, parts: {regex: bad}, reject: true}
    - {command: Item, provenance: {class: t.Item}, kind: single, parts: {regex: '\\w+'}}
"""
    text = HEADER + "contexts:\n  main:\n" + WORD + OPEN % "" + body
    (tmp_path / "toy.yaml").write_text(text, encoding="utf-8")
    models = resolve(load_dir(tmp_path))
    assert run(models, "open {", "ok", "bad", "}") == (False, (4, "bad"))


def test_reject_via_insert_before_over_unnarrowed_rule(tmp_path: Path) -> None:
    (tmp_path / "base.yaml").write_text(
        HEADER.replace("id: toy", "id: base")
        .replace("layer: diagram", "layer: shared")
        .replace("diagram: CLASS\n", "")
        + "contexts:\n  main:\n"
        + PAGE
        + CATCH_ALL
        + BODY,
        encoding="utf-8",
    )
    top = textwrap.dedent(
        """\
        schema_version: 1
        id: top
        layer: diagram
        diagram: CLASS
        include: [base]
        insert_before:
          Page:
            - {command: Zero, provenance: {class: t.Zero}, kind: single,
               parts: {regex: 'page 0'}, reject: true}
        """
    )
    (tmp_path / "top.yaml").write_text(top, encoding="utf-8")
    models = resolve(load_dir(tmp_path))
    verdict = Interpreter(models).accepts(uml("page 0"))
    assert (verdict["accepted"], verdict["model"]) == (False, None)
    assert Interpreter(models).accepts(uml("page 1"))["model"] == "top"


@pytest.mark.parametrize("lines", [("page 0",), ("x", "page 0")])
def test_reject_fails_at_first_failure_line(tmp_path: Path, lines: tuple[str, ...]) -> None:
    models = toy(tmp_path, REJECT + CATCH_ALL)
    accepted, failure = run(models, *lines)
    assert (accepted, failure) == (False, (len(lines) + 1, "page 0"))
