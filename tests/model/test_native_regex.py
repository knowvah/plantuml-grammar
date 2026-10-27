"""Proof that ``packages/engine/src/native-regex.ts`` recognises ``RX_WELL_FORMED`` exactly.

Expected: the Python ``regex`` fullmatch of the recursive leaf (``RX_WELL_FORMED`` in
``model/diagrams/meta-diagrams-regex.yaml``) compiled through ``tools.model.java_regex``.
Actual: ``regexWellFormedEnds(s, 0)`` contains ``s.length`` (UTF-16), evaluated in one Node
process per batch (Node strips the TypeScript types). The leaf has lookarounds and ``\\Z``,
so only "is the whole string a match" is compared, as for the data-invalid JSON leaf.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from tests.families.test_meta_diagrams_regex import PIECES, random_line
from tests.model.test_js_subroutines import (
    FIXTURES,
    WELL_FORMED,
    collect_candidates,
    model_pattern,
    python_original,
)
from tests.model.test_native_json import utf16_length
from tools.model.js_subroutines import REGEX_WELL_FORMED_KIND, fast_depth, native_kind
from tools.validate.corpus import enumerate_corpora

REPO = Path(__file__).resolve().parents[2]
NATIVE_TS = REPO / "packages" / "engine" / "src" / "native-regex.ts"
ENDS_FUNCTION = "regexWellFormedEnds"
NODE_TIMEOUT_S = 600
SEED = 2026
RANDOM_LINES = 4000
NUL = "\0"
# Hand-written edges: NUL ends the line, a line terminator may follow an unclosed class
# (the translated `\Z`), astral characters are one Java escape char but not a group name.
EDGES = [
    "",
    NUL,
    "a" + NUL,
    "a" + NUL + "garbage )(",
    "(a" + NUL + ")",
    "a\\" + NUL,
    "[a" + NUL,
    "[a" + NUL + "]",
    "(?#" + NUL + ")a",
    "\\p{" + NUL + "}",
    "a\n",
    "a\r\n",
    "a\r",
    "[ab",
    "[ab\n",
    "[ab\r\n",
    "[ab\r\nx",
    "[ab\n\n",
    "[a\\",
    "[a\\\n",
    "[\\]]",
    "[]",
    "[]]",
    "[[:alpha:]]",
    "[[:al",
    "[[:a:b",
    "[[:a:\nb",
    "\\0ab\n",
    "\\u00e9",
    "\\u00e",
    "\\p{L}",
    "\\p{L",
    "\\pL",
    "\\x{41}",
    "\\xA",
    "\\0𝐀bc",
    "\\𝐀",
    "𝐀+",
    "[𝐀]",
    "(?<𝐀>a)",
    "(?<é>a)",
    "(?<n1>a)",
    "(?<>a)",
    "(?<=a)b",
    "(?<!a)b",
    "(?=)",
    "(?!a)",
    "(?:?!a)",
    "(?:a)",
    "(?i)a",
    "(?#c)(?#d)a(?#e)",
    "(?#c",
    "a|",
    "|a",
    "a||b",
    "(a|)",
    "a*?",
    "a*??",
    "a???",
    "a{2}?",
    "a{,}",
    "a{}",
    "a{2",
    "a{2}{3}",
    "a{2}(?#c){3}",
    "*",
    "()",
    "(())",
    "((a))",
    "(a))",
    "((a)",
    ")(",
    "a b",
    " a",
    "a}",
    "a]",
    "a<b>",
    "^$",
    ".",
    "\\",
    "a\\",
]
NODE_SCRIPT = """
const [, nativePath, inputPath] = process.argv;
const native = await import(nativePath);
const fs = await import("node:fs");
const { inputs, name } = JSON.parse(fs.readFileSync(inputPath, "utf8"));
process.stdout.write(JSON.stringify(inputs.map((s) => native[name](s, 0))));
"""


def synthetic_inputs() -> list[str]:
    rng = random.Random(SEED)
    found = set(EDGES) | set(PIECES)
    found.update(a + b for a in PIECES for b in PIECES)
    found.update(random_line(rng) for _ in range(RANDOM_LINES))
    return sorted(found)


def run_node(inputs: list[str]) -> list[list[int]]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH; the native regex tests need Node.js")
    payload = {"inputs": inputs, "name": ENDS_FUNCTION}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "inputs.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        done = subprocess.run(  # noqa: S603 - fixed argv, trusted local file
            [node, "--input-type=module", "-e", NODE_SCRIPT, NATIVE_TS.as_uri(), str(path)],
            capture_output=True,
            text=True,
            check=True,
            timeout=NODE_TIMEOUT_S,
            cwd=REPO,
        )
    return json.loads(done.stdout)


def disagreements(inputs: list[str]) -> list[str]:
    """Inputs where the native ends and the Python fullmatch differ."""
    original = python_original(WELL_FORMED)
    return [
        f"{s!r}: python={original.fullmatch(s) is not None} native={found}"
        for s, found in zip(inputs, run_node(inputs), strict=True)
        if (utf16_length(s) in found) != (original.fullmatch(s) is not None)
    ]


def report(label: str, inputs: list[str], started: float) -> None:
    hits = sum(1 for s in inputs if python_original(WELL_FORMED).fullmatch(s))
    print(
        f"{label}: {len(inputs)} inputs, {hits} match, {time.monotonic() - started:.1f}s",
        file=sys.stderr,
    )


@pytest.fixture(scope="module")
def synthetic() -> list[str]:
    return synthetic_inputs()


def test_well_formed_is_the_native_regex_leaf_without_a_fast_regex():
    pattern = model_pattern(WELL_FORMED)
    assert native_kind(pattern) == REGEX_WELL_FORMED_KIND
    assert fast_depth(pattern) is None


def test_native_agrees_with_python_on_synthetic_inputs(synthetic):
    started = time.monotonic()
    assert disagreements(synthetic) == []
    report("synthetic", synthetic, started)


def test_synthetic_inputs_cover_both_verdicts(synthetic):
    verdicts = {python_original(WELL_FORMED).fullmatch(s) is not None for s in synthetic}
    assert verdicts == {True, False}


def test_native_agrees_with_python_on_fixture_lines():
    _, lines = collect_candidates(sorted(FIXTURES.rglob("*.puml")))
    assert lines
    assert disagreements(sorted(lines)) == []


@pytest.mark.corpus
def test_native_agrees_with_python_on_the_corpus():
    started = time.monotonic()
    paths = sorted(FIXTURES.rglob("*.puml")) + [p for _, p, _ in enumerate_corpora()]
    _, lines = collect_candidates(paths)
    inputs = sorted(lines)
    assert disagreements(inputs) == []
    report("corpus", inputs, started)
