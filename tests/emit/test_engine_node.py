"""Engine budget (D7) and Node-vs-Python equality on the JSON commands (D3a)."""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

from tests.emit.engine_support import (
    JSON_COMMANDS,
    PIN,
    Verdicts,
    block_texts,
    corpus_texts,
    engine_entries,
    entry,
    lit,
    nested,
    node_verdicts,
    single_line_texts,
    synthetic,
)
from tests.model.test_js_subroutines import FIXTURES
from tools.emit import engine as eng
from tools.interp.compile import compile_part
from tools.model import Part
from tools.validate.corpus import enumerate_corpora

# --- budget (D7) ---------------------------------------------------------------------------


def test_engine_file_size_and_cold_load_are_within_budget(engine_file):
    probe = eng.probe_engine(engine_file)
    assert engine_file.stat().st_size <= eng.MAX_BYTES
    assert probe.failures == []
    assert probe.loaded_patterns > 0
    assert probe.load_ms <= eng.MAX_LOAD_MS


def test_report_prints_sizes_counts_and_load_time(engine_file, capsys):
    eng.report_engine(engine_file)
    out = capsys.readouterr().out
    assert re.search(r"engine json: \d+ bytes raw, \d+ bytes gzip", out)
    assert re.search(r"patterns: \d+, contexts: \d+", out)
    assert "unsupported: 0" in out
    assert re.search(r"cold load .*: \d+ ms", out)


def test_report_fails_on_a_pattern_that_does_not_compile(tmp_path):
    bad = tmp_path / "bad.json"
    data = eng.build_engine(synthetic([entry(lit("a"))]), PIN)
    data["patterns"].append({"source": "(", "flags": "u"})
    bad.write_text(json.dumps(data))
    with pytest.raises(eng.EngineBuildError, match="do not compile"):
        eng.report_engine(bad)


def test_report_fails_over_budget(tmp_path, monkeypatch):
    path = tmp_path / "e.json"
    eng.write_engine(path, synthetic([entry(lit("a"))]))
    monkeypatch.setattr(eng, "MAX_BYTES", 10)
    with pytest.raises(eng.EngineBuildError, match="over budget"):
        eng.report_engine(path)


def test_probe_needs_node(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(eng.EngineBuildError, match="node"):
        eng.probe_engine(tmp_path / "x.json")


# --- Node equals Python on the JSON commands -----------------------------------------------


@pytest.fixture(scope="module")
def json_entries(resolved, built) -> dict[str, tuple[Part, int]]:
    """command -> (parts, engine pattern id), for the first model that has it."""
    found: dict[str, tuple[Part, int]] = {}
    for mid, name, index, source in engine_entries(resolved, built):
        if source["command"] in JSON_COMMANDS and source["command"] not in found:
            table = built["models"][mid]["contexts"][name]
            found[source["command"]] = (
                source["parts"],
                built["context_table"][table][index]["start"],
            )
    assert set(found) == set(JSON_COMMANDS)
    return found


def compare(
    entries: dict[str, tuple[Part, int]], engine_file: Path, dist: Path, texts: dict[str, list[str]]
) -> list[tuple[str, str, bool, bool]]:
    """Disagreements ``(command, text, python, node)``; one Node process for all texts."""
    wanted = {c: texts[c] for c in JSON_COMMANDS}
    jobs = {c: (entries[c][1], wanted[c]) for c in JSON_COMMANDS}
    node: Verdicts = node_verdicts(engine_file, dist, jobs)
    bad = []
    for command, lines in wanted.items():
        python = compile_part(entries[command][0])
        for line, verdict in zip(lines, node[command], strict=True):
            expected = python.fullmatch(line) is not None
            if expected != verdict:
                bad.append((command, line[:200], expected, verdict))
    return bad


def test_node_matches_python_on_nested_and_malformed_json(json_entries, engine_file, engine_dist):
    bodies = [b for k in (0, 1, 2, 3, 4, 5, 8, 12) for b in nested(k)]
    texts = {
        "CommandCreateJsonBlock": block_texts(bodies),
        "CommandCreateJsonSingleLineError": single_line_texts(bodies),
    }
    assert any(
        compile_part(json_entries[c][0]).fullmatch(t) for c in JSON_COMMANDS for t in texts[c]
    )
    assert compare(json_entries, engine_file, engine_dist, texts) == []


def collect_corpus_texts() -> dict[str, list[str]]:
    paths = sorted(FIXTURES.rglob("*.puml")) + [p for _, p, _ in enumerate_corpora()]
    return corpus_texts(paths)


@pytest.mark.corpus
def test_node_matches_python_on_corpus_and_fixture_json_lines(
    json_entries, engine_file, engine_dist
):
    texts = collect_corpus_texts()
    assert all(texts[c] for c in JSON_COMMANDS)
    bad = compare(json_entries, engine_file, engine_dist, texts)
    print({c: len(t) for c, t in texts.items()}, file=sys.stderr)
    assert bad == []
