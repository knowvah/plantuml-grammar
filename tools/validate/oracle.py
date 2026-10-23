"""SyntaxChecker oracle: per-block accept/reject verdicts with a content cache.

Contract I5. One JVM per run (cache misses only), JSON lines on stdout.
`error_line` is 1-based within the file text. `preproc` is the block's
preprocessed lines including the start and end directives.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from tools.config import PIN_SHA, require

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "reports" / "oracle-cache"
BUILD_DIR = REPO_ROOT / "build" / "java"
# Bump when Oracle.java verdict semantics change, so cached verdicts are not reused.
# 2: resolve !include relative to the source file (SourceFileReader.java:79).
ORACLE_VERSION = 2
MAIN_CLASS = "Oracle"
BUILD_HINT = "python -m tools.extract.build"
NO_VERDICT = "no verdict returned by oracle JVM"


class BlockVerdict(TypedDict):
    """One block's verdict; ``Oracle.java`` and ``_error_verdict`` write every key but ``error``."""

    index: int
    start_keyword: str
    accepted: bool
    diagram_type: str | None
    error_line: int | None
    preproc: list[str]
    error: NotRequired[str]  # additive: present only on harness-level failures


Runner = Callable[[Sequence[str]], Iterable[str]]


class OracleError(Exception):
    """The oracle JVM could not run or produced unusable output."""


def default_pin() -> str:
    return PIN_SHA


def parse_line(line: str) -> dict[str, Any]:
    try:
        parsed: dict[str, Any] = json.loads(line)
    except json.JSONDecodeError as err:
        raise OracleError(f"oracle output is not JSON: {line[:80]!r}") from err
    return parsed


def jvm_command(jar: Path, build_dir: Path) -> list[str]:
    return ["java", "-cp", f"{build_dir}:{jar}", MAIN_CLASS]


def ensure_built(build_dir: Path) -> None:
    if not (build_dir / f"{MAIN_CLASS}.class").exists():
        raise OracleError(f"{MAIN_CLASS}.class not found in {build_dir}; run {BUILD_HINT}")


def make_jvm_runner(cmd: list[str], popen: Callable[..., Any] = subprocess.Popen) -> Runner:
    def run(paths: Sequence[str]) -> Iterator[str]:
        with tempfile.TemporaryFile("w+") as stdin:
            stdin.write("".join(f"{p}\n" for p in paths))
            stdin.seek(0)
            proc = popen(
                cmd, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
            )
            for line in proc.stdout:
                yield line.rstrip("\n")
            proc.wait()
        if proc.returncode != 0:
            raise OracleError(f"oracle JVM exited with {proc.returncode}")

    return run


def default_runner() -> Runner:
    ensure_built(BUILD_DIR)
    return make_jvm_runner(jvm_command(require("jar"), BUILD_DIR))


def _error_verdict(message: str) -> list[BlockVerdict]:
    return [
        {
            "index": 0,
            "start_keyword": "",
            "accepted": False,
            "diagram_type": None,
            "error_line": None,
            "preproc": [],
            "error": message,
        }
    ]


def _cache_file(cache_dir: Path, path: Path, pin: str) -> Path:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return cache_dir / f"{digest}-{pin}-o{ORACLE_VERSION}.json"


def _load(cache_file: Path) -> list[BlockVerdict] | None:
    if not cache_file.exists():
        return None
    blocks: list[BlockVerdict] = json.loads(cache_file.read_text())
    return blocks


def _run_misses(misses: list[str], runner: Runner | None) -> dict[str, dict[str, Any]]:
    if not misses:
        return {}
    answers = (parse_line(line) for line in (runner or default_runner())(misses))
    return {a["path"]: a for a in answers}


def _store(answer: dict[str, Any] | None, cache_file: Path) -> list[BlockVerdict]:
    if answer is None:
        return _error_verdict(NO_VERDICT)
    if "error" in answer:
        return _error_verdict(str(answer["error"]))
    blocks: list[BlockVerdict] = answer["blocks"]
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(blocks))
    return blocks


def oracle_verdicts(
    paths: Sequence[Path],
    *,
    runner: Runner | None = None,
    cache_dir: Path | None = None,
    pin: str | None = None,
) -> dict[str, list[BlockVerdict]]:
    """Return `{str(path): [BlockVerdict, ...]}`; only cache misses reach the JVM."""
    cache_dir = cache_dir or CACHE_DIR
    pin = pin or default_pin()
    cached: dict[str, list[BlockVerdict]] = {}
    files: dict[str, Path] = {}
    for path in paths:
        key = str(path)
        files[key] = _cache_file(cache_dir, path, pin)
        hit = _load(files[key])
        if hit is not None:
            cached[key] = hit
    misses = [k for k in files if k not in cached]
    started = time.monotonic()
    answers = _run_misses(misses, runner)
    seconds = round(time.monotonic() - started, 3)
    result = {k: cached[k] if k in cached else _store(answers.get(k), files[k]) for k in files}
    _summarize(result, len(cached), seconds)
    return result


def _summarize(result: dict[str, list[BlockVerdict]], hits: int, seconds: float) -> None:
    summary = {
        "files": len(result),
        "blocks": sum(len(v) for v in result.values()),
        "cache_hits": hits,
        "jvm_seconds": seconds,
    }
    print(json.dumps(summary), file=sys.stderr)


def preproc(path: Path, block: int, **kwargs: Any) -> list[str]:
    """Preprocessed lines of one block, served from the verdict cache."""
    return oracle_verdicts([path], **kwargs)[str(path)][block]["preproc"]
