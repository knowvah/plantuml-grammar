"""End-to-end: build + run the extractor against the pinned jar (needs jar and upstream clone)."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from tools.config import PIN_SHA, require
from tools.extract import run

pytestmark = pytest.mark.corpus

BUILDER_PATH = "src/main/java/net/sourceforge/plantuml/PSystemBuilder.java"
BUILDER_FIRST_LINE, BUILDER_LAST_LINE = 133, 200
CONDITIONAL_FACTORY = "PSystemPathFactory"  # only registered under SecurityProfile.INSECURE
ADD_RE = re.compile(r"^\s*factories\.add\(new (\w+)\(\)\);")
CREATE_CLASS = "net.sourceforge.plantuml.classdiagram.command.CommandCreateClass"
CREATE_CLASS_LEAVES = {"TYPE", "GENERIC", "STEREO", "EXTENDS", "IMPLEMENTS"}
UNEXPANDED_MACRO = "%pLN"


def _run(out: Path) -> str:
    """Build and extract into `out`; returns the extractor's stderr."""
    captured: list[str] = []

    def runner(cmd: list[str]) -> int:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        captured.append(proc.stderr)
        return proc.returncode

    assert run.run_extractor(out=out, run=runner) == 0
    return captured[0]


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    first, second = tmp_path_factory.mktemp("a"), tmp_path_factory.mktemp("b")
    stderr = _run(first)
    _run(second)
    return first, second, stderr


GANTT_LANG = "gantt-lang"  # T03 sentence-part dump, not a factory document


def _docs(directory: Path) -> dict[str, dict]:
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in directory.glob("*.json")
        if p.stem != GANTT_LANG
    }


def _expected_factories() -> list[str]:
    src = require("src")
    text = subprocess.run(
        ["git", "-C", str(src), "show", f"{PIN_SHA}:{BUILDER_PATH}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    lines = text.splitlines()[BUILDER_FIRST_LINE - 1 : BUILDER_LAST_LINE]
    names = [m.group(1) for line in lines if (m := ADD_RE.match(line))]
    return [n for n in names if n != CONDITIONAL_FACTORY]


def _leaves(node: dict):
    yield node
    for child in node["children"]:
        yield from _leaves(child)


def test_one_file_per_factory_in_builder_order(runs):
    docs = _docs(runs[0])
    expected = _expected_factories()
    assert sorted(docs) == sorted(expected)
    assert [docs[name]["factoryOrder"] for name in expected] == list(range(len(expected)))
    assert docs["ClassDiagramFactory"]["factoryOrder"] == 3
    assert docs["ClassDiagramFactory"]["diagramType"] == "CLASS"


def test_pin_matches_upstream_pin_file(runs):
    pin = json.loads((run.REPO_ROOT / "upstream-pin.json").read_text())
    doc = _docs(runs[0])["ClassDiagramFactory"]
    assert doc["pin"] == {"sha": pin["sha"], "version": pin["version"]}


def test_create_class_has_named_leaves(runs):
    commands = _docs(runs[0])["ClassDiagramFactory"]["commands"]
    create = next(c for c in commands if c["class"] == CREATE_CLASS)
    assert create["kind"] == "single"
    assert create["engine"] == "IRegex"
    names = {n["name"] for n in _leaves(create["start"]) if n["t"] == "leaf"}
    assert CREATE_CLASS_LEAVES <= names


def test_percent_macros_stay_unexpanded(runs):
    commands = _docs(runs[0])["ClassDiagramFactory"]["commands"]
    patterns = [
        n["pattern"]
        for c in commands
        if c["start"]
        for n in _leaves(c["start"])
        if n["t"] == "leaf" and n["pattern"] and "[%pLN_]" in n["pattern"]
    ]
    assert patterns, "expected a leaf containing [%pLN_]"
    assert all(UNEXPANDED_MACRO in p and "\\p{L}" not in p for p in patterns)


def test_two_runs_are_byte_identical_and_end_with_newline(runs):
    first, second, _ = runs
    names = sorted(p.name for p in first.glob("*.json"))
    assert names == sorted(p.name for p in second.glob("*.json"))
    for name in names:
        data = (first / name).read_bytes()
        assert data == (second / name).read_bytes()
        assert data.endswith(b"}\n")


def test_every_unwalked_command_is_listed_unreachable(runs):
    for doc in _docs(runs[0]).values():
        listed = {(u["class"], u["order"]) for u in doc["unreachable"]}
        assert all(u["reason"] for u in doc["unreachable"])
        for c in doc["commands"]:
            if c["start"] is None:
                assert (c["class"], c["order"]) in listed, c["class"]


def test_ubrex_commands_walked_or_listed_unreachable(runs):
    """After T03, UBrex commands carry ub-* trees; only NaturalGanttCommand stays unreachable."""
    docs = _docs(runs[0])
    ubrex = [c for d in docs.values() for c in d["commands"] if c["engine"] == "UBrex"]
    assert ubrex
    unreachable = {(u["class"], u["order"]) for d in docs.values() for u in d["unreachable"]}
    for c in ubrex:
        if c["start"] is None:
            assert (c["class"], c["order"]) in unreachable
        else:
            assert c["start"]["t"].startswith("ub-")
    reasons = {u["reason"] for d in docs.values() for u in d["unreachable"]}
    assert "ubrex-pending" not in reasons


def test_gantt_shadowing_field_resolved_from_base_class(runs):
    commands = _docs(runs[0])["GanttDiagramFactory"]["commands"]
    between = next(c for c in commands if c["class"].endswith(".CommandPrintBetween"))
    assert between["engine"] == "UBrex"
    assert between["start"]["t"].startswith("ub-")


def test_multiline_commands_carry_start_and_end(runs):
    commands = _docs(runs[0])["ClassDiagramFactory"]["commands"]
    multi = [c for c in commands if c["kind"] == "multiline" and c["end"] is not None]
    assert multi
    assert all(
        c["start"]["t"] and c["end"]["t"] == "leaf" for c in multi if c["engine"] == "IRegex"
    )


def test_opaque_factory_with_regex_and_without(runs):
    docs = _docs(runs[0])
    colors = docs["PSystemColorsFactory"]["commands"]
    assert [(c["kind"], c["start"]["name"]) for c in colors] == [("opaque", "pattern")]
    assert colors[0]["start"]["pattern"] == "^colors?\\s*(#?\\w+)?\\s*$"
    json_doc = docs["JsonDiagramFactory"]
    assert json_doc["commands"] == []
    assert [u["reason"] for u in json_doc["unreachable"]] == ["opaque-no-regex-field"]


def test_stderr_is_one_json_summary_line(runs):
    lines = runs[2].strip().splitlines()
    assert len(lines) == 1
    summary = json.loads(lines[0])
    docs = _docs(runs[0])
    assert summary["factories"] == len(docs)
    assert summary["commands"]["ClassDiagramFactory"] == len(
        docs["ClassDiagramFactory"]["commands"]
    )
    assert summary["unreachable"] == sum(len(d["unreachable"]) for d in docs.values())
