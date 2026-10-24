"""Judge parity jobs with the TypeScript engine through its JSONL CLI (contract C6).

``run_ts`` mirrors ``parity_run.run_interp``: it returns one ``(l2, raw)`` Outcome per job, in
job order. Each job becomes one L2 request and, when ``use_raw`` is set and the job has a raw
block, one raw request; the CLI answers every request line in input order, and the answers
are paired back by request id. Environment problems (no ``node`` or ``npm``, a failed build,
a missing engine JSON, a CLI that dies or hangs) raise ``TsEngineError``.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess  # noqa: S404 - runs the repo's own node CLI with an argument list
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.interp import Verdict
from tools.validate.parity_run import Job, Outcome, RunConfig, error_verdict

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "packages" / "engine"
CLI_JS = PACKAGE_DIR / "dist" / "cli.js"
SRC_DIR = PACKAGE_DIR / "src"
ENGINE_JSON = REPO_ROOT / "dist" / "plantuml.engine.json"
BUILD_ARGS = ("run", "build", "-w", "packages/engine")
KILL_GRACE_S = 2.0  # the pool kills a worker at timeout_s + 2 s
STARTUP_SLACK_S = 30.0  # node start-up, engine load and lazy regex compilation
BUILD_TIMEOUT_S = 300.0
TAIL_CHARS = 2000
KIND_L2 = "l2"
KIND_RAW = "raw"
ID_SEP = ":"
MISSING_RESULT = "ts engine returned no result for this request"
LOG = logging.getLogger("tools.validate.ts_engine")


class TsEngineError(Exception):
    """The TypeScript engine could not be built, started or read."""


@dataclass(frozen=True)
class Request:
    """One CLI input line: ``id`` is ``<job index>:<l2|raw>``."""

    id: str
    text: str
    raw: bool


def _tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise TsEngineError(f"{name} is not on PATH; the typescript engine needs Node.js")
    return path


def _newest_source(src: Path) -> float:
    return max((p.stat().st_mtime for p in src.rglob("*.ts")), default=0.0)


def needs_build(cli: Path = CLI_JS, src: Path = SRC_DIR) -> bool:
    """Is the compiled CLI missing or older than the newest TypeScript source?"""
    return not cli.exists() or cli.stat().st_mtime < _newest_source(src)


def _tail(text: str) -> str:
    return text.strip()[-TAIL_CHARS:]


def _run(
    args: Sequence[str], payload: str | None, timeout_s: float
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 - fixed argument list, no shell
            list(args),
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=REPO_ROOT,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as err:
        raise TsEngineError(f"{Path(args[0]).name} exceeded {timeout_s:.0f}s") from err
    except OSError as err:
        raise TsEngineError(f"cannot run {args[0]}: {err}") from err


def ensure_built() -> None:
    """Build ``packages/engine`` when ``dist/cli.js`` is stale or absent."""
    if not needs_build():
        return
    done = _run((_tool("npm"), *BUILD_ARGS), None, BUILD_TIMEOUT_S)
    if done.returncode != 0:
        LOG.error("engine build failed: %s", _tail(done.stdout + done.stderr))
        raise TsEngineError(
            f"npm {' '.join(BUILD_ARGS)} failed ({done.returncode}): {_tail(done.stdout)}"
        )


def build_requests(jobs: Sequence[Job], use_raw: bool) -> list[Request]:
    """L2 request per job, then a raw request when raw judging applies to it."""
    requests: list[Request] = []
    for i, job in enumerate(jobs):
        requests.append(Request(f"{i}{ID_SEP}{KIND_L2}", job.text, False))
        if use_raw and job.raw_text is not None:
            requests.append(Request(f"{i}{ID_SEP}{KIND_RAW}", job.raw_text, True))
    return requests


def encode_requests(requests: Sequence[Request], timeout_s: float) -> str:
    """The JSONL stdin payload."""
    lines = (
        json.dumps({"id": r.id, "text": r.text, "raw": r.raw, "timeout_s": timeout_s})
        for r in requests
    )
    return "".join(f"{line}\n" for line in lines)


def decode_results(stdout: str) -> dict[str, Verdict]:
    """Verdicts by request id from the CLI's stdout."""
    found: dict[str, Verdict] = {}
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            row: dict[str, Any] = json.loads(line)
            found[str(row["id"])] = row["verdict"]
        except (ValueError, KeyError, TypeError) as err:
            raise TsEngineError(f"unreadable result line from the ts engine: {line[:200]}") from err
    return found


def pair_outcomes(
    jobs: Sequence[Job], requests: Sequence[Request], found: dict[str, Verdict]
) -> list[Outcome]:
    """Fold the per-request verdicts back into one ``(l2, raw)`` per job."""
    wanted = {r.id for r in requests}

    def get(i: int, kind: str) -> Verdict | None:
        key = f"{i}{ID_SEP}{kind}"
        if key not in wanted:
            return None
        return found.get(key) or error_verdict(MISSING_RESULT)

    return [
        (get(i, KIND_L2) or error_verdict(MISSING_RESULT), get(i, KIND_RAW))
        for i in range(len(jobs))
    ]


def run_timeout_s(count: int, timeout_s: float, workers: int) -> float:
    """Whole-run budget: requests x (timeout + 2 s) / workers, plus start-up slack."""
    return count * (timeout_s + KILL_GRACE_S) / max(workers, 1) + STARTUP_SLACK_S


def run_ts(
    jobs: Sequence[Job], config: RunConfig, workers: int = 1, *, engine: Path = ENGINE_JSON
) -> list[Outcome]:
    """Outcomes in job order from ``node packages/engine/dist/cli.js`` (see module docs)."""
    if not jobs:
        return []
    node = _tool("node")
    if not engine.exists():
        raise TsEngineError(f"engine json not found: {engine}")
    ensure_built()
    requests = build_requests(jobs, config.use_raw)
    payload = encode_requests(requests, config.timeout_s)
    budget = run_timeout_s(len(requests), config.timeout_s, workers)
    args = (node, str(CLI_JS), "--engine", str(engine), "--workers", str(max(workers, 1)))
    done = _run(args, payload, budget)
    if done.returncode != 0:
        LOG.error("ts engine exited %s: %s", done.returncode, _tail(done.stderr))
        raise TsEngineError(f"ts engine exited {done.returncode}: {_tail(done.stderr)}")
    return pair_outcomes(jobs, requests, decode_results(done.stdout))
