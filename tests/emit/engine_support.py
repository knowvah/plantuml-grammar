"""Helpers for ``test_engine*.py``: shared models and fixtures, JSON command inputs, Node runs."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from tests.model.test_native_json import BASES, nested
from tools.emit import engine as eng
from tools.interp.source import split_block, split_blocks
from tools.model import Entry, Part, ResolvedModel, ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve

REPO = Path(__file__).resolve().parents[2]
PIN = "0123456789abcdef"
JSON_COMMANDS = ("CommandCreateJsonBlock", "CommandCreateJsonSingleLineError")
JOINER = ""
HEADS = ["json j {", 'json "d e" as j {', "json j #red {", "json  j  <<s>> {"]
SINGLE_HEADS = ["json j ", "json  j  ", 'json "d" as j ']
TAILS = ["}", "} ", "}x"]
BLOCK_COMMAND = "CommandCreateJsonBlock"
SINGLE_COMMAND = "CommandCreateJsonSingleLineError"
MAX_WINDOW = 300
MAX_CLOSERS = 3
NODE_TIMEOUT_S = 600
NODE_SCRIPT = """
import { pathToFileURL } from "node:url";
import { readFileSync } from "node:fs";
const [, enginePath, distPath, jobsPath] = process.argv;
const { loadEngine } = await import(pathToFileURL(distPath + "/load.js").href);
const { Deadline } = await import(pathToFileURL(distPath + "/deadline.js").href);
const engine = loadEngine(JSON.parse(readFileSync(enginePath, "utf8")));
const jobs = JSON.parse(readFileSync(jobsPath, "utf8"));
const out = {};
for (const [name, { id, texts }] of Object.entries(jobs)) {
  const matcher = engine.matcher(id);
  out[name] = texts.map((t) => matcher.test(t, new Deadline(600000)));
}
process.stdout.write(JSON.stringify(out));
"""

Verdicts = dict[str, list[bool]]
__all__ = [
    "PIN",
    "REPO",
    "JSON_COMMANDS",
    "Verdicts",
    "block_texts",
    "corpus_texts",
    "engine_entries",
    "nested",
    "node_verdicts",
    "single_line_texts",
]


def engine_entries(
    resolved: ResolvedModels, built: dict[str, Any]
) -> Iterator[tuple[str, str, int, Entry]]:
    """``(model id, context name, index, resolved entry)`` in engine order."""
    for mid in built["model_order"]:
        for name, entries in resolved[mid].contexts.items():
            for index, entry in enumerate(entries):
                yield mid, name, index, entry


def block_texts(bodies: Sequence[str]) -> list[str]:
    """Joined ``json`` block texts: head, joiner, optional body and joiner, closing brace."""
    texts = [f"{head}{JOINER}{tail}" for head in HEADS for tail in TAILS]
    for body in [*bodies, *BASES]:
        texts += [f"{HEADS[0]}{JOINER}{body}{JOINER}{tail}" for tail in TAILS]
        texts.append(f"{HEADS[0]}{JOINER}{body}{JOINER}")
        texts.append(f"{HEADS[1]}{JOINER}{body}{JOINER}}}")
    return texts


def single_line_texts(bodies: Sequence[str]) -> list[str]:
    """``json name DATA`` lines for the single-line error command."""
    return [head + body for head in SINGLE_HEADS for body in [*bodies, *BASES]]


def corpus_texts(paths: Sequence[Path]) -> dict[str, list[str]]:
    """Every line starting with ``json`` and every joined window to a closing ``}``."""
    singles: set[str] = set()
    blocks: set[str] = set()
    for path in paths:
        text = path.read_text(errors="replace")
        if "json" not in text.lower():
            continue
        for block in split_blocks(text):
            lines = [line.trimmed for line in split_block(block).body]
            for i, line in enumerate(lines):
                if line.lower().startswith("json"):
                    singles.add(line)
                    blocks.update(windows(lines, i))
    return {BLOCK_COMMAND: sorted(blocks), SINGLE_COMMAND: sorted(singles)}


def windows(lines: list[str], start: int) -> Iterator[str]:
    closers = 0
    for j in range(start + 1, min(len(lines), start + MAX_WINDOW)):
        if lines[j].startswith("}"):
            yield JOINER.join(lines[start : j + 1])
            closers += 1
            if closers == MAX_CLOSERS:
                return


def node_verdicts(
    engine_file: Path, dist: Path, jobs: dict[str, tuple[int, list[str]]]
) -> Verdicts:
    """Run ``engine.matcher(id).test`` for every text, in one Node process."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH")
    payload = {name: {"id": pid, "texts": texts} for name, (pid, texts) in jobs.items()}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "jobs.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        done = subprocess.run(  # noqa: S603 - fixed argv, trusted local files
            [
                node,
                "--input-type=module",
                "-e",
                NODE_SCRIPT,
                str(engine_file),
                str(dist),
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=NODE_TIMEOUT_S,
        )
    result: Verdicts = json.loads(done.stdout)
    return result


def lit(text: str) -> Part:
    return {"literal": text}


def rx(source: str) -> Part:
    return {"regex": source}


def synthetic(entries: list[Entry], factory: str | None = None) -> ResolvedModels:
    model = ResolvedModel(
        id="m",
        layer="diagram",
        path=None,
        diagram="X",
        variables={},
        contexts={"main": entries},
        factory=factory,
    )
    return {"m": model}


def entry(parts: Part, **extra: Any) -> Entry:
    return {"command": "Cmd", "kind": "single", "parts": parts, **extra}


@pytest.fixture(scope="session")
def resolved() -> ResolvedModels:
    return resolve(load_dir(REPO / "model"))


@pytest.fixture(scope="session")
def built(resolved: ResolvedModels) -> dict[str, Any]:
    return eng.build_engine(resolved, PIN)


@pytest.fixture(scope="session")
def engine_file(resolved: ResolvedModels, tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("engine") / "plantuml.engine.json"
    eng.write_engine(path, resolved)
    return path


@pytest.fixture(scope="session")
def engine_dist() -> Path:
    npm = shutil.which("npm")
    if npm is None:
        pytest.skip("npm is not on PATH")
    done = subprocess.run(  # noqa: S603 - fixed argv
        [npm, "run", "build", "-w", "packages/engine"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return REPO / "packages" / "engine" / "dist"
