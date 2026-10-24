"""Record the Python interpreter's verdicts as conformance goldens for the TS engine (C5, D9).

``uv run python -m tools.validate.conformance [--check]`` judges every ``@start...@end`` block
of every ``tests/fixtures/**/*.puml`` file with ``tools.interp.accepts`` (default dispatch, no
start map, default timeout) in both ``raw`` modes, and writes ``tests/conformance/fixtures.jsonl``.
The toy model sets of ``tests/conformance/toy_specs.py`` get an engine JSON and a JSONL each
under ``tests/conformance/toy/``. ``--check`` regenerates in memory and exits 1 on drift.

Fixtures are judged in a forked worker pool; a verdict with status ``timeout`` is retried with
longer timeouts so that every golden is decisive (the case is logged to stderr).
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tools.emit.engine import read_pin, render_engine
from tools.interp import STATUS_TIMEOUT, Verdict, accepts
from tools.interp.source import split_blocks
from tools.model import ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve

ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = ROOT / "tests" / "fixtures"
MODEL_DIR = ROOT / "model"
GOLDEN_DIR = ROOT / "tests" / "conformance"
FIXTURES_FILE = "fixtures.jsonl"
TOY_DIR = "toy"
PUML_GLOB = "*.puml"
ENCODING = "utf-8"
RAW_MODES = (False, True)
RETRY_TIMEOUTS_S = (60.0, 600.0)
CHUNK_SIZE = 4
EXIT_OK = 0
EXIT_DRIFT = 1
MAX_REPORTED = 20

Record = dict[str, Any]
Key = tuple[str, int, bool]

_MODELS: ResolvedModels = {}


def decisive(
    models: ResolvedModels,
    text: str,
    raw: bool,
    start_map: Mapping[str, Sequence[str]] | None = None,
) -> tuple[Verdict, float | None]:
    """The verdict, retried with longer timeouts on ``timeout``; also the timeout that decided."""
    verdict = accepts(models, text, raw=raw, start_map=start_map)
    raised: float | None = None
    for timeout_s in RETRY_TIMEOUTS_S:
        if verdict["status"] != STATUS_TIMEOUT:
            break
        raised = timeout_s
        verdict = accepts(models, text, raw=raw, start_map=start_map, timeout_s=timeout_s)
    return verdict, raised


def fixture_records(path: Path, rel: str) -> list[Record]:
    """Goldens of one fixture file: one per (block, raw), in order."""
    text = path.read_text(encoding=ENCODING, errors="replace")
    records: list[Record] = []
    for index, block in enumerate(split_blocks(text)):
        for raw in RAW_MODES:
            verdict, raised = decisive(_MODELS, block, raw)
            record: Record = {"fixture": rel, "block": index, "raw": raw, "verdict": verdict}
            if raised is not None:
                print(
                    f"timeout raised to {raised}s: {rel} block {index} raw={raw}", file=sys.stderr
                )
            records.append(record)
    return records


def _work(rel: str) -> list[Record]:
    return fixture_records(ROOT / rel, rel)


def fixture_paths() -> list[str]:
    """Repo-relative POSIX paths of every fixture, sorted."""
    return sorted(p.relative_to(ROOT).as_posix() for p in FIXTURES_DIR.rglob(PUML_GLOB))


def all_fixture_records(models: ResolvedModels, jobs: int) -> list[Record]:
    """Goldens for every fixture, judged by ``jobs`` forked workers (1: in this process)."""
    global _MODELS
    _MODELS = models
    paths = fixture_paths()
    if jobs <= 1:
        results = [_work(p) for p in paths]
    else:
        with multiprocessing.get_context("fork").Pool(jobs) as pool:
            results = pool.map(_work, paths, chunksize=CHUNK_SIZE)
    return [record for per_file in results for record in per_file]


def dump_line(record: Record) -> str:
    return json.dumps(record, sort_keys=True)


def jsonl(records: Sequence[Record]) -> str:
    return "".join(f"{dump_line(r)}\n" for r in records)


def toy_files() -> dict[str, str]:
    """Relative golden path -> text for every toy set."""
    from tests.conformance.toy_specs import TOY_SPECS

    files: dict[str, str] = {}
    pin = read_pin()
    for spec in TOY_SPECS:
        with tempfile.TemporaryDirectory() as tmp:
            models = spec.build(Path(tmp))
            files[f"{TOY_DIR}/{spec.name}.engine.json"] = render_engine(models, pin)
            records: list[Record] = []
            for index, case in enumerate(spec.cases):
                for raw in RAW_MODES:
                    verdict, _ = decisive(models, case.text, raw, case.start_map)
                    record: Record = {
                        "fixture": f"{TOY_DIR}/{spec.name}",
                        "block": index,
                        "raw": raw,
                        "text": case.text,
                        "verdict": verdict,
                    }
                    if case.start_map is not None:
                        record["start_map"] = case.start_map
                    records.append(record)
            files[f"{TOY_DIR}/{spec.name}.jsonl"] = jsonl(records)
    return files


def generate(jobs: int) -> tuple[dict[str, str], list[Record]]:
    """All golden files (relative path -> text) and the fixture records."""
    models = resolve(load_dir(MODEL_DIR))
    records = all_fixture_records(models, jobs)
    files = {FIXTURES_FILE: jsonl(records), **toy_files()}
    return files, records


def _keyed(text: str) -> dict[Key, str]:
    keyed: dict[Key, str] = {}
    for line in filter(None, text.splitlines()):
        rec = json.loads(line)
        keyed[(rec["fixture"], rec["block"], rec["raw"])] = line
    return keyed


def diff_files(expected: Mapping[str, str], actual: Mapping[str, str]) -> list[str]:
    """Human-readable drift lines between committed (``expected``) and regenerated files."""
    out: list[str] = []
    for name in sorted(set(expected) | set(actual)):
        if name not in actual:
            out.append(f"{name}: not generated any more")
        elif name not in expected:
            out.append(f"{name}: missing from the committed goldens")
        elif expected[name] != actual[name]:
            out.extend(_diff_file(name, expected[name], actual[name]))
    return out


def _diff_file(name: str, old: str, new: str) -> list[str]:
    if not name.endswith(".jsonl"):
        return [f"{name}: differs"]
    before, after = _keyed(old), _keyed(new)
    out = [
        f"{name}: case {k} changed"
        for k in sorted(before.keys() & after.keys())
        if before[k] != after[k]
    ]
    out += [f"{name}: case {k} no longer generated" for k in sorted(before.keys() - after.keys())]
    out += [f"{name}: case {k} not committed" for k in sorted(after.keys() - before.keys())]
    return out or [f"{name}: differs"]


def committed(directory: Path | None = None) -> dict[str, str]:
    """The golden files on disk, keyed like ``generate``."""
    directory = directory or GOLDEN_DIR
    found: dict[str, str] = {}
    path = directory / FIXTURES_FILE
    if path.is_file():
        found[FIXTURES_FILE] = path.read_text(encoding=ENCODING)
    toy = directory / TOY_DIR
    if toy.is_dir():
        for path in sorted(toy.iterdir()):
            found[f"{TOY_DIR}/{path.name}"] = path.read_text(encoding=ENCODING)
    return found


def write_files(files: Mapping[str, str], directory: Path | None = None) -> None:
    directory = directory or GOLDEN_DIR
    (directory / TOY_DIR).mkdir(parents=True, exist_ok=True)
    stale = set(committed(directory)) - set(files)
    for rel in stale:
        (directory / rel).unlink()
    for rel, text in files.items():
        (directory / rel).write_text(text, encoding=ENCODING, newline="\n")


def report(records: Sequence[Record], seconds: float) -> None:
    histogram = Counter(r["verdict"]["status"] for r in records)
    summary = ", ".join(f"{status}={n}" for status, n in sorted(histogram.items()))
    print(f"cases: {len(records)}; status: {summary}; time: {seconds:.1f}s")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.validate.conformance")
    parser.add_argument("--check", action="store_true", help="exit 1 if the goldens drifted")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    args = parser.parse_args(argv)
    start = time.monotonic()
    files, records = generate(args.jobs)
    report(records, time.monotonic() - start)
    if not args.check:
        write_files(files)
        return EXIT_OK
    drift = diff_files(committed(), files)
    for line in drift[:MAX_REPORTED]:
        print(line, file=sys.stderr)
    if len(drift) > MAX_REPORTED:
        print(f"... and {len(drift) - MAX_REPORTED} more", file=sys.stderr)
    return EXIT_DRIFT if drift else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
