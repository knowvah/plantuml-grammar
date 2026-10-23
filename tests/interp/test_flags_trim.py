"""Diagram flags (``gives``/``needs``) and untrimmed matching (``trim: false``) on toy models."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.interp import accepts
from tools.interp.source import read_line, split_block
from tools.model import ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve

from .helpers import failure_of, uml

HEADER = "schema_version: 1\nid: toy\nlayer: diagram\ndiagram: CLASS\n"
END_LINE = "@enduml"
FLAG = "real_task"


def single(name: str, regex: str, **extra: str) -> str:
    tail = "".join(f", {key}: {value}" for key, value in extra.items())
    return (
        f"    - {{command: {name}, provenance: {{class: t.{name}}}, kind: single,"
        f" parts: {{regex: '{regex}'}}{tail}}}\n"
    )


SEP = single("Sep", "-- \\w+ --", needs=FLAG)
TASK = single("Task", "task \\w+", gives=FLAG)
GROUP = single("Group", "grp \\{", push="group", needs=FLAG)
OPEN = single("Open", "open \\{", push="body", require_pop="true")
PLAIN = single("Plain", "open.*")
ANY = single("Any", ".+")
GROUP_CTX = "  group:\n" + single("Close", "\\}", pop="true") + TASK
BODY_CTX = (
    "  body:\n"
    + single("BodyClose", "\\}", pop="true")
    + single("BodyTask", "task \\w+", gives=FLAG)
    + single("BodySep", "-- \\w+ --", needs=FLAG)
)


def toy(tmp_path: Path, main: str, *contexts: str) -> ResolvedModels:
    text = HEADER + "contexts:\n  main:\n" + main + "".join(contexts)
    (tmp_path / "toy.yaml").write_text(text, encoding="utf-8")
    return resolve(load_dir(tmp_path))


def run(models: ResolvedModels, *lines: str) -> tuple[bool, tuple[int, str] | None]:
    verdict = accepts(models, uml(*lines))
    return verdict["accepted"], None if verdict["accepted"] else failure_of(verdict)


# --- gives / needs -------------------------------------------------------------------------


def test_needs_without_give_fails_at_the_end_line(tmp_path: Path) -> None:
    models = toy(tmp_path, SEP + TASK)
    assert run(models, "-- a --") == (False, (3, END_LINE))


def test_give_after_the_need_satisfies_it(tmp_path: Path) -> None:
    models = toy(tmp_path, SEP + TASK)
    assert run(models, "-- a --", "task x") == (True, None)


def test_give_before_the_need_satisfies_it(tmp_path: Path) -> None:
    models = toy(tmp_path, SEP + TASK)
    assert run(models, "task x", "-- a --") == (True, None)


def test_flags_do_nothing_when_nothing_needs_them(tmp_path: Path) -> None:
    models = toy(tmp_path, SEP + TASK)
    assert run(models, "task x") == (True, None)


def test_several_needs_are_all_satisfied_by_one_give(tmp_path: Path) -> None:
    models = toy(tmp_path, SEP + TASK)
    assert run(models, "-- a --", "-- b --", "task x") == (True, None)


def test_a_give_of_another_flag_does_not_satisfy(tmp_path: Path) -> None:
    other = single("Other", "other", gives="something_else")
    models = toy(tmp_path, SEP + other)
    assert run(models, "-- a --", "other") == (False, (4, END_LINE))


def test_syntax_errors_win_over_the_final_state_check(tmp_path: Path) -> None:
    models = toy(tmp_path, SEP + TASK)
    assert run(models, "-- a --", "nope") == (False, (3, "nope"))


def test_flag_given_inside_a_pushed_context_counts_after_the_pop(tmp_path: Path) -> None:
    models = toy(tmp_path, SEP + GROUP + TASK, GROUP_CTX)
    assert run(models, "-- a --", "grp {", "task x", "}") == (True, None)


def test_group_with_no_task_inside_fails_at_the_end_line(tmp_path: Path) -> None:
    models = toy(tmp_path, SEP + GROUP + TASK, GROUP_CTX)
    assert run(models, "grp {", "}") == (False, (4, END_LINE))


def test_backtrack_discards_a_give_made_inside_the_abandoned_body(tmp_path: Path) -> None:
    # `open {` never closes, so the push is abandoned; `Plain` takes the line and `task x`
    # is then read by `Any`, which gives nothing: the give made in the body is gone.
    models = toy(tmp_path, SEP + OPEN + PLAIN + ANY, BODY_CTX)
    assert run(models, "-- a --", "open {", "task x") == (False, (5, END_LINE))


def test_backtrack_keeps_gives_made_before_the_push(tmp_path: Path) -> None:
    models = toy(tmp_path, SEP + TASK + OPEN + PLAIN + ANY, BODY_CTX)
    assert run(models, "-- a --", "task x", "open {", "task y") == (True, None)


def test_backtrack_discards_a_need_made_inside_the_abandoned_body(tmp_path: Path) -> None:
    models = toy(tmp_path, OPEN + PLAIN + ANY, BODY_CTX)
    assert run(models, "open {", "-- a --") == (True, None)


def test_closed_body_keeps_its_give(tmp_path: Path) -> None:
    models = toy(tmp_path, SEP + OPEN + PLAIN + ANY, BODY_CTX)
    assert run(models, "-- a --", "open {", "task x", "}") == (True, None)


def test_reject_entry_with_flags_still_fails_at_its_line(tmp_path: Path) -> None:
    bad = single("Bad", "bad", reject="true", gives=FLAG)
    models = toy(tmp_path, SEP + bad + ANY)
    assert run(models, "-- a --", "bad") == (False, (3, "bad"))


def test_flag_failure_reports_the_last_line_without_an_end_directive(tmp_path: Path) -> None:
    models = toy(tmp_path, SEP + TASK)
    verdict = accepts(models, "@startuml\n-- a --")
    assert (verdict["accepted"], failure_of(verdict)) == (False, (2, "-- a --"))


def test_preproc_entries_do_not_contribute_in_raw_mode(tmp_path: Path) -> None:
    pre = (
        "schema_version: 1\nid: pre\nlayer: preproc\ncontexts:\n  main:\n"
        + single("PreTask", "!task", gives=FLAG)
        + single("PreSep", "!sep", needs=FLAG)
    )
    (tmp_path / "pre.yaml").write_text(pre, encoding="utf-8")
    models = toy(tmp_path, SEP + TASK)
    raw = accepts(models, uml("!task", "-- a --"), raw=True)
    assert (raw["accepted"], failure_of(raw)) == (False, (4, END_LINE))
    ok = accepts(models, uml("!sep", "task x"), raw=True)
    assert ok["accepted"] is True


# --- trim: false ---------------------------------------------------------------------------

PLUS = single("Plus", "\\+\\+ \\w+", trim="false")
DASH = single("Dash", "-- \\w+")
TRIM_CASES = [
    ("++ b", True),
    ("  ++ b", False),
    ("\t++ b", False),
    ("++ b ", False),
    ("++ b\t", False),
    (" ++ b", False),
]


@pytest.mark.parametrize(("line", "ok"), TRIM_CASES)
def test_untrimmed_rule_matches_the_raw_line(tmp_path: Path, line: str, ok: bool) -> None:
    models = toy(tmp_path, PLUS)
    assert run(models, line)[0] is ok


def test_untrimmed_failure_reports_the_raw_text(tmp_path: Path) -> None:
    models = toy(tmp_path, PLUS)
    assert run(models, "  ++ b") == (False, (2, "  ++ b"))


def test_default_rules_still_match_the_trimmed_line(tmp_path: Path) -> None:
    models = toy(tmp_path, PLUS + DASH)
    assert run(models, "  -- b  ", "\t-- c") == (True, None)


def test_trailing_carriage_return_is_not_part_of_the_line(tmp_path: Path) -> None:
    models = toy(tmp_path, PLUS)
    verdict = accepts(models, "@startuml\r\n++ b\r\n@enduml\r\n")
    assert verdict["accepted"] is True


def test_untrimmed_rule_is_skipped_so_a_later_rule_can_take_the_line(tmp_path: Path) -> None:
    models = toy(tmp_path, PLUS + ANY)
    assert run(models, "  ++ b") == (True, None)


def test_trim_applies_to_override_patches(tmp_path: Path) -> None:
    text = HEADER + "overrides:\n  Dash: {trim: false}\ncontexts:\n  main:\n" + DASH
    (tmp_path / "toy.yaml").write_text(text, encoding="utf-8")
    models = resolve(load_dir(tmp_path))
    assert run(models, "-- b") == (True, None)
    assert run(models, " -- b") == (False, (2, " -- b"))


# --- the raw text mirrors ReadLineReader.readLine ------------------------------------------


@pytest.mark.parametrize(
    ("raw", "text"),
    [
        ("﻿++ b", "++ b"),
        ("a–b", "a-b"),
        ("a﻿b", "a﻿b"),
        ("\t x \t", "\t x \t"),
    ],
)
def test_read_line_mirrors_read_line_reader(raw: str, text: str) -> None:
    assert read_line(raw) == text


def test_split_block_breaks_lines_like_buffered_reader() -> None:
    block = split_block("@startuml\r\n–x\rb\n@enduml")
    assert [(ln.number, ln.text) for ln in block.body] == [(2, "-x"), (3, "b")]


# --- corpus: the jar agrees on the raw text and on untrimmed commands ----------------------

MODEL_DIR = Path(__file__).resolve().parents[2] / "model"
JAR_CASES = [
    ("tab-trailing", "@startmindmap\n* a\n++ b\t\n@endmindmap\n", True),
    ("tab-leading", "@startmindmap\n* a\n\t++ b\n@endmindmap\n", False),
    ("blank-leading", "@startmindmap\n* a\n  ++ b\n@endmindmap\n", False),
    ("crlf", "@startmindmap\r\n* a\r\n++ b\r\n@endmindmap\r\n", True),
    ("en-dash", "@startmindmap\n* a\n–– b\n@endmindmap\n", True),
    ("wbs-trailing-blank", "@startwbs\n* root\n**_ \n@endwbs\n", False),
]


@pytest.mark.corpus
def test_untrimmed_matching_agrees_with_the_jar(tmp_path: Path) -> None:
    from tools.validate.oracle import oracle_verdicts

    paths = []
    for name, text, _ in JAR_CASES:
        path = tmp_path / f"{name}.puml"
        path.write_bytes(text.encode("utf-8"))
        paths.append(path)
    jar = oracle_verdicts(paths)
    models = resolve(load_dir(MODEL_DIR))
    for path, (name, text, expected) in zip(paths, JAR_CASES, strict=True):
        assert jar[str(path)][0]["accepted"] is expected, name
        assert accepts(models, text)["accepted"] is expected, name
