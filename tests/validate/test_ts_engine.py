"""ts_engine: request/result pairing, environment errors, and a real Node round trip."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.engine_build import build_engine_once
from tests.helpers.models import repo_resolved
from tools.validate import ts_engine
from tools.validate.parity_run import RunConfig, error_verdict, judge
from tools.validate.ts_engine import Request, TsEngineError

from .parity_helpers import BAD_BLOCK, GOOD_BLOCK, job, verdict

CONFIG = RunConfig(Path("model"), 10.0, True)
NODE = shutil.which("node")


def test_requests_pair_l2_with_raw_only_when_raw_applies():
    jobs = [job("a", "x", oracle=True), job("b", "y", oracle=True)]
    jobs[1] = type(jobs[1])(jobs[1].path, 0, "y", None, True, "CLASS")
    reqs = ts_engine.build_requests(jobs, use_raw=True)
    assert [(r.id, r.text, r.raw) for r in reqs] == [
        ("0:l2", "x", False),
        ("0:raw", "x", True),
        ("1:l2", "y", False),
    ]
    assert [r.id for r in ts_engine.build_requests(jobs, use_raw=False)] == ["0:l2", "1:l2"]


def test_encode_requests_is_jsonl_with_timeout():
    payload = ts_engine.encode_requests([Request("0:l2", "a\nb", False)], 4.5)
    assert payload.endswith("\n")
    assert json.loads(payload) == {"id": "0:l2", "text": "a\nb", "raw": False, "timeout_s": 4.5}


def test_decode_results_rejects_garbage():
    ok = json.dumps({"id": "0:l2", "verdict": verdict(True)})
    assert ts_engine.decode_results(f"{ok}\n\n") == {"0:l2": verdict(True)}
    with pytest.raises(TsEngineError, match="unreadable result line"):
        ts_engine.decode_results("not json\n")
    with pytest.raises(TsEngineError, match="unreadable"):
        ts_engine.decode_results('{"id": "x"}\n')


def test_pair_outcomes_fills_missing_results_with_error_verdicts():
    jobs = [job("a", "x", oracle=True), job("b", "y", oracle=True)]
    reqs = ts_engine.build_requests(jobs, use_raw=True)
    found = {"0:l2": verdict(True), "0:raw": verdict(False), "1:l2": verdict(True)}
    outcomes = ts_engine.pair_outcomes(jobs, reqs, found)
    assert outcomes[0] == (verdict(True), verdict(False))
    assert outcomes[1] == (verdict(True), error_verdict(ts_engine.MISSING_RESULT))
    missing = ts_engine.pair_outcomes(jobs[:1], reqs[:2], {})
    assert missing == [(error_verdict(ts_engine.MISSING_RESULT),) * 2]


def test_run_timeout_scales_with_jobs_and_workers():
    assert ts_engine.run_timeout_s(8, 10.0, 4) == 8 * 12.0 / 4 + ts_engine.STARTUP_SLACK_S
    assert ts_engine.run_timeout_s(1, 1.0, 0) == 3.0 + ts_engine.STARTUP_SLACK_S


def test_needs_build_compares_mtimes(tmp_path: Path):
    src, cli = tmp_path / "src", tmp_path / "cli.js"
    src.mkdir()
    (src / "a.ts").write_text("x", encoding="utf-8")
    assert ts_engine.needs_build(cli, src)
    cli.write_text("x", encoding="utf-8")
    newest = (src / "a.ts").stat().st_mtime
    os.utime(cli, (newest + 5, newest + 5))
    assert not ts_engine.needs_build(cli, src)
    os.utime(cli, (newest - 5, newest - 5))
    assert ts_engine.needs_build(cli, src)


def test_missing_node_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ts_engine.shutil, "which", lambda _name: None)
    with pytest.raises(TsEngineError, match="node is not on PATH"):
        ts_engine.run_ts([job("a", GOOD_BLOCK, oracle=True)], CONFIG)


def test_no_jobs_needs_no_node(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ts_engine.shutil, "which", lambda _name: None)
    assert ts_engine.run_ts([], CONFIG) == []


def test_missing_engine_json_raises(tmp_path: Path):
    with pytest.raises(TsEngineError, match="engine json not found"):
        ts_engine.run_ts([job("a", "x", oracle=True)], CONFIG, engine=tmp_path / "none.json")


def _completed(code: int, out: str = "", err: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, out, err)


def _patch_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, runs: list) -> Path:
    engine = tmp_path / "e.json"
    engine.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ts_engine.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(ts_engine, "needs_build", lambda *a: False)
    monkeypatch.setattr(ts_engine, "_run", lambda args, payload, t: runs.pop(0))
    return engine


def test_run_ts_pairs_results_from_the_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    reply = "".join(
        json.dumps({"id": i, "verdict": verdict(i == "0:l2")}) + "\n" for i in ("0:l2", "0:raw")
    )
    engine = _patch_env(monkeypatch, tmp_path, [_completed(0, reply)])
    out = ts_engine.run_ts([job("a", "x", oracle=True)], CONFIG, 2, engine=engine)
    assert out == [(verdict(True), verdict(False))]


def test_cli_failure_raises_with_stderr(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    engine = _patch_env(monkeypatch, tmp_path, [_completed(1, "", "engine load failed")])
    with pytest.raises(TsEngineError, match="exited 1: engine load failed"):
        ts_engine.run_ts([job("a", "x", oracle=True)], CONFIG, engine=engine)


def test_build_runs_when_stale_and_failure_raises(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, ...]] = []

    def fake(args, payload, timeout):
        calls.append(tuple(args))
        return _completed(1, "tsc said no")

    monkeypatch.setattr(ts_engine.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(ts_engine, "needs_build", lambda *a: True)
    monkeypatch.setattr(ts_engine, "_run", fake)
    with pytest.raises(TsEngineError, match="failed \\(1\\): tsc said no"):
        ts_engine.ensure_built()
    assert calls == [("/bin/npm", "run", "build", "-w", "packages/engine")]


def test_build_skipped_when_fresh(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ts_engine, "needs_build", lambda *a: False)
    monkeypatch.setattr(ts_engine, "_run", lambda *a: pytest.fail("must not build"))
    ts_engine.ensure_built()


def test_run_wraps_timeout_and_oserror(monkeypatch: pytest.MonkeyPatch):
    def hang(*_a, **_k):
        raise subprocess.TimeoutExpired("node", 1)

    monkeypatch.setattr(ts_engine.subprocess, "run", hang)
    with pytest.raises(TsEngineError, match="node exceeded 1s"):
        ts_engine._run(["/bin/node"], None, 1.0)

    def missing(*_a, **_k):
        raise FileNotFoundError("gone")

    monkeypatch.setattr(ts_engine.subprocess, "run", missing)
    with pytest.raises(TsEngineError, match="cannot run /bin/node"):
        ts_engine._run(["/bin/node"], None, 1.0)


@pytest.mark.skipif(NODE is None, reason="node is not on PATH")
@pytest.mark.skipif(not ts_engine.ENGINE_JSON.exists(), reason="dist/plantuml.engine.json absent")
def test_real_cli_agrees_with_python_on_three_jobs():
    jobs = [
        job("good", GOOD_BLOCK, oracle=True),
        job("bad", BAD_BLOCK, oracle=False),
        job("good2", "@startuml\nA -> B : hi\n@enduml", oracle=True, otype="SEQUENCE"),
    ]
    config = RunConfig(ts_engine.REPO_ROOT / "model", 30.0, True)
    expected = [judge(repo_resolved(), j, config) for j in jobs]
    assert [e[0]["accepted"] for e in expected] == [True, False, True]
    build_engine_once()  # run_ts would build too; this one is safe across xdist workers
    assert ts_engine.run_ts(jobs, config, 2) == expected
