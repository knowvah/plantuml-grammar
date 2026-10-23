"""Coverage matrix: modeled / partial / excluded / missing."""

import json
from pathlib import Path

from tools.model.load import load_dir
from tools.model.resolve import resolve
from tools.report import coverage

FACTORY = "ToyFactory"
PKG = "net.toy."


def _command(order, name, kind="single"):
    return {"order": order, "class": PKG + name, "kind": kind}


def write_extracted(directory: Path) -> None:
    doc = {
        "factory": FACTORY,
        "diagramType": "CLASS",
        "commands": [
            _command(0, "CommandDone"),
            _command(1, "CommandNoRule"),
            _command(2, "CommandTwice"),
            _command(3, "CommandTwice"),
            _command(4, "CommandOpaque", "opaque"),
            _command(5, "CommandSkipped"),
        ],
        "unreachable": [{"order": 6, "class": PKG + "Natural", "reason": "natural-sentence"}],
    }
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{FACTORY}.json").write_text(json.dumps(doc), encoding="utf-8")
    (directory / "gantt-lang.json").write_text(json.dumps({"variables": {}}), encoding="utf-8")
    (directory / "OtherFactory.json").write_text(
        json.dumps(
            {
                "factory": "OtherFactory",
                "diagramType": "X",
                "commands": [_command(0, "A")],
                "unreachable": [],
            }
        ),
        encoding="utf-8",
    )


def write_models(directory: Path) -> None:
    def rule(name, kind="single"):
        return (
            f"    - command: {name}\n      provenance: {{class: {PKG}{name}}}\n"
            f"      kind: {kind}\n      parts: {{regex: x}}\n"
        )

    body = (
        "schema_version: 1\nid: toy\nlayer: diagram\ndiagram: CLASS\n"
        f"factory: {FACTORY}\ncontexts:\n  main:\n"
        + rule("CommandDone")
        + rule("CommandTwice")
        + rule("CommandOpaque", "opaque").replace("regex: x", "regex: y")
    )
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "toy.yaml").write_text(body, encoding="utf-8")


def test_statuses_for_every_case(tmp_path: Path):
    write_extracted(tmp_path / "extracted")
    write_models(tmp_path / "model")
    classify = tmp_path / "classify"
    classify.mkdir()
    (classify / "toy.yaml").write_text(
        "exclusions:\n  CommandSkipped: not reachable from text\n"
        f"  {PKG}Other: {{reason: ignored}}\n  Natural: sentence grammar\n",
        encoding="utf-8",
    )
    extracted = coverage.load_extracted(tmp_path / "extracted")
    assert sorted(extracted) == ["OtherFactory", FACTORY]
    models = resolve(load_dir(tmp_path / "model"))
    matrix = coverage.build_matrix(extracted, models, coverage.load_exclusions(classify))
    status = {c.simple: (c.status, c.note) for c in matrix[FACTORY]}
    assert status == {
        "CommandDone": ("modeled", ""),
        "CommandNoRule": ("missing", ""),
        "CommandTwice": ("partial", ""),
        "CommandOpaque": ("partial", ""),
        "CommandSkipped": ("excluded", "not reachable from text"),
        "Natural": ("excluded", "sentence grammar"),
    }
    assert [c.status for c in matrix["OtherFactory"]] == ["missing"]


def test_unreachable_without_exclusion_is_missing_with_extractor_reason():
    doc = {
        "commands": [],
        "unreachable": [{"order": 0, "class": "a.B", "reason": "opaque-no-regex-field"}],
    }
    [command] = coverage.classify_commands(doc, coverage.Counter(), {})
    assert (command.status, command.note, command.kind) == (
        "missing",
        "opaque-no-regex-field",
        "unreachable",
    )


def test_load_exclusions_handles_absent_dir_and_empty_files(tmp_path: Path):
    assert coverage.load_exclusions(tmp_path / "nope") == {}
    (tmp_path / "a.yaml").write_text("", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("- list\n", encoding="utf-8")
    (tmp_path / "c.yaml").write_text("cases: {}\n", encoding="utf-8")
    assert coverage.load_exclusions(tmp_path) == {}


def test_generate_and_cli_write_markdown(tmp_path: Path, capsys, monkeypatch):
    write_extracted(tmp_path / "extracted")
    write_models(tmp_path / "model")
    text = coverage.generate(tmp_path / "extracted", tmp_path / "model", tmp_path / "none")
    assert "| ToyFactory | CLASS | unclassified | 1 | 3 | 3 | 0 |" in text
    assert "| 1 | CommandNoRule | single | missing |" in text
    assert "| 6 | Natural | unreachable | missing |" in text
    monkeypatch.setattr(coverage, "generate", lambda: text)
    out = tmp_path / "docs" / "coverage.md"
    assert coverage.main(["--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == text
    assert str(out) in capsys.readouterr().err


def test_excluded_label_names_the_reason():
    command = coverage.Command(0, "a.B", "single", "excluded", "why")
    text = coverage.render({"F": [command]}, {"F": "D"})
    assert "| 0 | B | single | excluded (why) |" in text


def test_partial_label_names_the_reason():
    command = coverage.Command(0, "a.B", "unreachable", "partial", "opaque-no-regex-field")
    text = coverage.render({"F": [command]}, {"F": "D"})
    assert "| 0 | B | unreachable | partial (opaque-no-regex-field) |" in text


def test_modeled_label_stays_plain_even_with_a_note():
    command = coverage.Command(0, "a.B", "unreachable", "modeled", "natural-sentence")
    text = coverage.render({"F": [command]}, {"F": "D"})
    assert "| 0 | B | unreachable | modeled |" in text
