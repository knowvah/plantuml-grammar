"""``{{`` gluing is a command-factory rule; ``empty_needs_end`` refuses truncated blocks."""

from __future__ import annotations

from pathlib import Path

from tools.interp import accepts
from tools.model import ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve

from .helpers import failure_of, uml

JOINER = ""
STYLE = f"<style>(?:{JOINER}[^{JOINER}]*)*{JOINER}</style>"
FACTORY_LINE = "factory: {}\n"
HEADER = "schema_version: 1\nid: toy\nlayer: diagram\ndiagram: CLASS\n"


def entry(name: str, parts: str, extra: str = "") -> str:
    return (
        f"    - {{command: {name}, provenance: {{class: t.{name}}}, kind: single,"
        f" parts: {{regex: '{parts}'}}{extra}}}\n"
    )


def toy(tmp_path: Path, text: str) -> ResolvedModels:
    (tmp_path / "toy.yaml").write_text(text, encoding="utf-8")
    return resolve(load_dir(tmp_path))


def style_model(tmp_path: Path, factory: str) -> ResolvedModels:
    join = (
        "    - command: Style\n      provenance: {class: t.Style}\n      kind: multiline\n"
        f"      join: {{max_lines: 10}}\n      parts: {{regex: '{STYLE}'}}\n"
    )
    text = (
        HEADER
        + FACTORY_LINE.format(factory)
        + "contexts:\n  main:\n"
        + join
        + entry("Tail", "tail")
    )
    return toy(tmp_path, text)


GLUED_BODY = ("<style>", "{{", "a", "</style>", "tail")


def test_command_factory_glues_an_embedded_unit_so_the_join_cannot_stop(tmp_path: Path) -> None:
    # "{{" swallows everything after it (no "}}"), so the joined text ends in "tail".
    verdict = accepts(style_model(tmp_path, "ClassDiagramFactory"), uml(*GLUED_BODY))
    assert (verdict["accepted"], failure_of(verdict)) == (False, (2, "<style>"))


def test_plain_line_factory_joins_across_a_brace_line(tmp_path: Path) -> None:
    verdict = accepts(style_model(tmp_path, "JsonDiagramFactory"), uml(*GLUED_BODY))
    assert (verdict["accepted"], verdict["model"]) == (True, "toy")


def test_plain_line_factory_still_rejects_an_unclosed_region(tmp_path: Path) -> None:
    verdict = accepts(style_model(tmp_path, "JsonDiagramFactory"), uml("<style>", "{{", "a"))
    assert (verdict["accepted"], failure_of(verdict)) == (False, (2, "<style>"))


def welcome(tmp_path: Path, needs_end: bool) -> ResolvedModels:
    key = "empty_needs_end: true\n" if needs_end else ""
    text = (
        HEADER
        + FACTORY_LINE.format("PSystemWelcomeFactory")
        + key
        + "contexts:\n  main: []\n  empty:\n"
        + entry("EndLine", "[@\\\\]end.*")
    )
    return toy(tmp_path, text)


def test_truncated_empty_block_is_accepted_without_the_key(tmp_path: Path) -> None:
    models = welcome(tmp_path, needs_end=False)
    assert accepts(models, "@startuml")["accepted"] is True
    assert accepts(models, "@startuml\n@enduml")["accepted"] is True


def test_truncated_empty_block_is_refused_with_the_key(tmp_path: Path) -> None:
    models = welcome(tmp_path, needs_end=True)
    verdict = accepts(models, "@startuml")
    assert (verdict["accepted"], failure_of(verdict)) == (False, (1, "@startuml"))
    assert accepts(models, "@startuml\n@enduml")["accepted"] is True


def test_a_bare_body_without_start_or_end_stays_accepted(tmp_path: Path) -> None:
    assert accepts(welcome(tmp_path, needs_end=True), "")["accepted"] is True
