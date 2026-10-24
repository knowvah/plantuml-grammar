"""The conformance goldens (C5) are current, decisive and well formed."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.conformance.toy_specs import TOY_SPECS
from tests.interp.conftest import FIXTURES as TOY_YAML
from tools.emit.engine import EngineBuildError, probe_engine
from tools.interp.source import split_blocks
from tools.model import ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve
from tools.validate import conformance as conf

VERDICT_KEYS = {"accepted", "diagram", "first_failure", "model", "status"}
TIMEOUT_STATUS = "timeout"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture(scope="module")
def regenerated() -> tuple[dict[str, str], list[dict[str, Any]]]:
    return conf.generate(os.cpu_count() or 1)


@pytest.fixture
def stub_generate(
    monkeypatch: pytest.MonkeyPatch, regenerated: tuple[dict[str, str], list[dict[str, Any]]]
) -> None:
    monkeypatch.setattr(conf, "generate", lambda jobs: regenerated)


@pytest.fixture
def golden_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copytree(conf.GOLDEN_DIR, tmp_path / "g", ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(conf, "GOLDEN_DIR", tmp_path / "g")
    return tmp_path / "g"


# --- the committed goldens ------------------------------------------------------------------


def test_regenerating_reproduces_the_committed_goldens(
    regenerated: tuple[dict[str, str], list[dict[str, Any]]],
) -> None:
    files, _ = regenerated
    assert conf.diff_files(conf.committed(), files) == []


def test_check_exits_zero_on_the_committed_goldens(
    stub_generate: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert conf.main(["--check"]) == conf.EXIT_OK
    assert "status: ok=" in capsys.readouterr().out


def test_one_golden_line_per_fixture_block_and_raw_mode(
    regenerated: tuple[dict[str, str], list[dict[str, Any]]],
) -> None:
    keys = [
        (r["fixture"], r["block"], r["raw"]) for r in read_jsonl(conf.GOLDEN_DIR / "fixtures.jsonl")
    ]
    expected = [
        (rel, index, raw)
        for rel in conf.fixture_paths()
        for index in range(len(split_blocks((conf.ROOT / rel).read_text(errors="replace"))))
        for raw in (False, True)
    ]
    assert keys == expected
    assert keys == sorted(keys)


def test_verdicts_have_exactly_the_i3_shape_and_none_timed_out() -> None:
    for record in read_jsonl(conf.GOLDEN_DIR / "fixtures.jsonl"):
        verdict = record["verdict"]
        assert set(verdict) == VERDICT_KEYS
        assert verdict["status"] != TIMEOUT_STATUS
        failure = verdict["first_failure"]
        assert failure is None or set(failure) == {"line", "text"}
        assert (failure is None) == verdict["accepted"]


def test_a_known_fixture_is_accepted_by_its_family() -> None:
    records = read_jsonl(conf.GOLDEN_DIR / "fixtures.jsonl")
    sequence = [r for r in records if r["fixture"].startswith("tests/fixtures/sequence/pos/")]
    assert sequence
    assert all(r["verdict"]["accepted"] for r in sequence[:20])
    assert {r["verdict"]["model"] for r in sequence[:20]} <= {"sequence", None}


# --- drift detection ------------------------------------------------------------------------


def flip_first_verdict(text: str) -> tuple[str, dict[str, Any]]:
    lines = text.splitlines()
    record = json.loads(lines[0])
    record["verdict"]["accepted"] = not record["verdict"]["accepted"]
    lines[0] = conf.dump_line(record)
    return "\n".join(lines) + "\n", record


def test_diff_names_a_changed_case() -> None:
    old = (conf.GOLDEN_DIR / "fixtures.jsonl").read_text(encoding="utf-8")
    new, record = flip_first_verdict(old)
    key = (record["fixture"], record["block"], record["raw"])
    assert conf.diff_files({"fixtures.jsonl": old}, {"fixtures.jsonl": new}) == [
        f"fixtures.jsonl: case {key} changed"
    ]


def test_diff_reports_added_removed_and_unchanged_files() -> None:
    assert conf.diff_files({"a": "1", "b": "2"}, {"b": "2", "c": "3"}) == [
        "a: not generated any more",
        "c: missing from the committed goldens",
    ]
    assert conf.diff_files({"x.engine.json": "1"}, {"x.engine.json": "2"}) == [
        "x.engine.json: differs"
    ]


def test_diff_reports_cases_dropped_or_added() -> None:
    line = conf.dump_line({"fixture": "f", "block": 0, "raw": False, "verdict": {}})
    other = conf.dump_line({"fixture": "f", "block": 1, "raw": False, "verdict": {}})
    assert conf.diff_files({"t.jsonl": line + "\n"}, {"t.jsonl": other + "\n"}) == [
        "t.jsonl: case ('f', 0, False) no longer generated",
        "t.jsonl: case ('f', 1, False) not committed",
    ]
    assert conf.diff_files({"t.jsonl": line + "\n"}, {"t.jsonl": line + "\n\n"}) == [
        "t.jsonl: differs"
    ]


def test_check_exits_one_and_names_the_edited_golden(
    stub_generate: None, golden_copy: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = golden_copy / "fixtures.jsonl"
    new, record = flip_first_verdict(path.read_text(encoding="utf-8"))
    path.write_text(new, encoding="utf-8")
    assert conf.main(["--check"]) == conf.EXIT_DRIFT
    key = (record["fixture"], record["block"], record["raw"])
    assert f"fixtures.jsonl: case {key} changed" in capsys.readouterr().err


def test_check_truncates_a_long_drift_report(
    stub_generate: None, golden_copy: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (golden_copy / "fixtures.jsonl").write_text("", encoding="utf-8")
    assert conf.main(["--check"]) == conf.EXIT_DRIFT
    err = capsys.readouterr().err.splitlines()
    assert len(err) == conf.MAX_REPORTED + 1
    assert err[-1].startswith("... and ")


def test_default_run_rewrites_goldens_and_removes_stale_toy_files(
    stub_generate: None, golden_copy: Path
) -> None:
    stale = golden_copy / "toy" / "gone.jsonl"
    stale.write_text("x\n", encoding="utf-8")
    (golden_copy / "fixtures.jsonl").write_text("", encoding="utf-8")
    assert conf.main([]) == conf.EXIT_OK
    assert not stale.exists()
    assert conf.diff_files(conf.committed(), conf.committed(conf.GOLDEN_DIR)) == []
    assert (golden_copy / "fixtures.jsonl").stat().st_size > 0


# --- timeouts are made decisive -------------------------------------------------------------


def verdict(status: str) -> dict[str, Any]:
    return {
        "accepted": status != "reject",
        "diagram": None,
        "first_failure": None,
        "model": None,
        "status": status,
    }


def test_timeouts_are_retried_with_longer_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[float] = []

    def fake(models: ResolvedModels, text: str, **kw: Any) -> dict[str, Any]:
        seen.append(kw.get("timeout_s", 0.0))
        return verdict("timeout" if len(seen) < 2 else "ok")

    monkeypatch.setattr(conf, "accepts", fake)
    result, raised = conf.decisive({}, "x", False)
    assert (result["status"], raised, seen) == ("ok", conf.RETRY_TIMEOUTS_S[0], [0.0, 60.0])


def test_a_verdict_that_stays_timeout_is_returned_after_the_last_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(conf, "accepts", lambda *a, **k: verdict("timeout"))
    result, raised = conf.decisive({}, "x", True)
    assert (result["status"], raised) == (TIMEOUT_STATUS, conf.RETRY_TIMEOUTS_S[-1])


def test_fixture_records_log_a_raised_timeout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = tmp_path / "t.puml"
    path.write_text("@startuml\nx\n@enduml\n", encoding="utf-8")
    monkeypatch.setattr(conf, "decisive", lambda *a, **k: (verdict("ok"), 60.0))
    records = conf.fixture_records(path, "t.puml")
    assert [(r["block"], r["raw"]) for r in records] == [(0, False), (0, True)]
    assert "timeout raised to 60.0s: t.puml block 0 raw=False" in capsys.readouterr().err


def test_serial_and_parallel_workers_agree(monkeypatch: pytest.MonkeyPatch) -> None:
    toy = resolve(load_dir(TOY_YAML))
    names = conf.fixture_paths()[:6]
    monkeypatch.setattr(conf, "fixture_paths", lambda: names)
    serial = conf.all_fixture_records(toy, 1)
    parallel = conf.all_fixture_records(toy, 2)
    assert serial == parallel
    assert {r["fixture"] for r in serial} <= set(names)


# --- toy sets -------------------------------------------------------------------------------


def test_toy_files_are_deterministic_and_complete() -> None:
    first = conf.toy_files()
    assert first == conf.toy_files()
    names = sorted(spec.name for spec in TOY_SPECS)
    assert sorted(first) == sorted(
        f"toy/{n}.{ext}" for n in names for ext in ("engine.json", "jsonl")
    )


def test_toy_cases_carry_text_and_both_raw_modes() -> None:
    records = read_jsonl(conf.GOLDEN_DIR / "toy" / "toys.jsonl")
    first = [r for r in records if r["block"] == 0]
    assert [(r["fixture"], r["raw"], r["text"]) for r in first] == [
        ("toy/toys", False, "@startuml\nalpha x\n@enduml"),
        ("toy/toys", True, "@startuml\nalpha x\n@enduml"),
    ]
    assert first[0]["verdict"] == {
        "accepted": True,
        "diagram": "SEQUENCE",
        "first_failure": None,
        "model": "seqtoy",
        "status": "ok",
    }
    assert all("start_map" not in r for r in first)


def test_toy_start_map_is_recorded_and_applied() -> None:
    records = read_jsonl(conf.GOLDEN_DIR / "toy" / "require-pop.jsonl")
    case = next(r for r in records if r["text"].endswith("open {\n@enduml") and not r["raw"])
    assert case["start_map"] == {"uml": ["rp-open"]}
    assert case["verdict"]["first_failure"] == {"line": 2, "text": "open {"}
    assert case["verdict"]["accepted"] is False


def test_toy_statuses_are_never_error_or_timeout() -> None:
    for path in (conf.GOLDEN_DIR / "toy").glob("*.jsonl"):
        for record in read_jsonl(path):
            assert record["verdict"]["status"] in {"ok", "reject"}, path.name


# --- engine JSON (C1) -----------------------------------------------------------------------

ENTRY_KEYS = {"command", "kind", "start", "action", "target", "require_pop", "reject"}
ENGINE_FILES = sorted((conf.GOLDEN_DIR / "toy").glob("*.engine.json"))


def check_c1(data: dict[str, Any]) -> None:
    assert data["engine_format"] == 1
    patterns = data["patterns"]
    assert all({"source", "flags"} <= set(p) or "unsupported" in p for p in patterns)
    assert not [p for p in patterns if "unsupported" in p]
    table = data["context_table"]
    assert sorted(data["model_order"]) == sorted(data["models"])
    for model in data["models"].values():
        assert model["layer"] in {"document", "preproc", "diagram", "shared"}
        assert all(0 <= index < len(table) for index in model["contexts"].values())
    for entries in table:
        for entry in entries:
            assert ENTRY_KEYS <= set(entry)
            assert 0 <= entry["start"] < len(patterns)
            assert entry["action"] in {"", "push", "pop", "set"}
            if "join" in entry:
                assert 0 <= entry["join"]["prefix"] < len(patterns)
    assert set(data["tops"].values()) <= set(data["models"])


@pytest.mark.parametrize("path", ENGINE_FILES, ids=lambda p: p.name)
def test_toy_engine_json_validates_against_c1(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    check_c1(data)
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_every_toy_set_has_an_engine_json() -> None:
    assert [p.name for p in ENGINE_FILES] == sorted(f"{s.name}.engine.json" for s in TOY_SPECS)


def test_toy_engine_patterns_compile_in_node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not on PATH")
    for path in ENGINE_FILES:
        try:
            probe = probe_engine(path)
        except EngineBuildError as err:  # pragma: no cover - failure message only
            pytest.fail(f"{path.name}: {err}")
        assert probe.failures == [], path.name
