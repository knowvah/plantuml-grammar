"""Proof that ``packages/engine/src/native.ts`` recognises the two JSON leaves exactly.

Expected: the Python ``regex`` fullmatch of the original recursive leaf
(``CO_JSON_BLOCK_BODY`` / ``CO_JSON_DATA_INVALID``, ``model/diagrams/class-objects.yaml:45-56``)
compiled through ``tools.model.java_regex.to_python``. Actual: ``jsonXxxEnds(s, 0)`` contains
``s.length``, evaluated in one Node process per batch (Node strips the TypeScript types).
The block-body leaf has no lookaround, so for short BMP inputs the full end set is also
compared against ``fullmatch(s, 0, j)`` for every ``j``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.model.test_js_subroutines import (
    FIXTURES,
    JSON_BLOCK,
    JSON_INVALID,
    collect_candidates,
    model_pattern,
    python_original,
)
from tools.validate.corpus import enumerate_corpora

REPO = Path(__file__).resolve().parents[2]
NATIVE_TS = REPO / "packages" / "engine" / "src" / "native.ts"
NODE_TIMEOUT_S = 600
JOINER = ""
MAX_NESTING = 40
ENDS_FUNCTIONS = {JSON_BLOCK: "jsonBlockBodyEnds", JSON_INVALID: "jsonDataInvalidEnds"}
MAX_FULL_ENDS_LENGTH = 40
JUNK = ['"', "\\", "{", "}", "[", "]", ",", ":", " ", "\n", "-", "0", "e", "“", "x", "\x85"]
NODE_SCRIPT = """
const [, nativePath, inputPath] = process.argv;
const native = await import(nativePath);
const fs = await import("node:fs");
const { inputs, names } = JSON.parse(fs.readFileSync(inputPath, "utf8"));
const out = {};
for (const [leaf, fn] of Object.entries(names)) {
  out[leaf] = inputs.map((s) => native[fn](s, 0));
}
process.stdout.write(JSON.stringify(out));
"""


def nested(k: int) -> Iterator[str]:
    """Arrays, objects and mixed nesting ``k`` deep, plus near misses."""
    yield "[" * k + "1" + "]" * k
    yield '{"a":' * k + "1" + "}" * k
    yield "".join('[{"a":' if n % 2 == 0 else "[" for n in range(k)) + "null" + "]" * k
    yield "[" * k + "1" + "]" * (k - 1)
    yield "[" * k + "1" + "]" * (k + 1)
    yield '{"a":' * k + "1" + "}" * (k - 1) + "]"
    yield "[" * k + "1,]" + "]" * (k - 1)
    yield f"{'[' * k}{JOINER}1{JOINER}{']' * k}"


BASES = [
    "",
    " ",
    JOINER,
    "0",
    "-0",
    "-",
    "01",
    "-01",
    "12",
    "1.5",
    "1.",
    ".5",
    "1e5",
    "1E+5",
    "1e",
    "1.5e-3",
    "0.0e0",
    "true",
    "TRUE",
    "tRuE",
    "false",
    "False",
    "null",
    "NULL",
    "nul",
    "truefalse",
    "t r u e",
    '"abc"',
    '"a\\"b"',
    '"a\\xb"',
    '"a\\u00e9b"',
    '"a\\u00zb"',
    '"a\nb"',
    '"a\tb"',
    '"é中\U0001f600"',
    '"unterminated',
    '"a" "b"',
    '"a"b"',
    "[]",
    "[ ]",
    "[1]",
    "[1,2]",
    "[1,]",
    "[,1]",
    "[1 2]",
    "[1,[2,[3]]]",
    '[1.5, -2, true, null, "x"]',
    "[1]]",
    "[[1]",
    "{}",
    "{ }",
    '{"a":1}',
    '{"a" : 1 , "b" : [1, 2]}',
    '{"a":1,}',
    '{"a"}',
    "{a:1}",
    '{"a":}',
    '{"a":1 "b":2}',
    '{"a":1}}',
    '{"a":{"b":{"c":[]}}}',
    '{"a\\"b":1}',
    "{“a”:1}",
    '{"a": 1.5 }',
    '{ "a" : 1 }',
    '{ "a" :1}',
    "{“a\\”b”: x }",
    '{"a\\": 1}',
    '{"a\\"": 1}',
    '{"\\": "x"}',
    '{"": 1}',
    '{"a" 1}',
    '{"a":x}',
    '{"a":x}\n',
    '{"a":1}x',
    '{"a":1}\n',
    '{"a":1}\n}',
    '{"a":"b\n}"}',
    "{a: x}",
    '{"a":""}: }',
    "x",
    "123abc",
    "-12",
    "-12.5",
    "1\n",
    "1\n2",
    "true\n",
    "TRUE\x85",
    "TRUE x",
    '"a"\r',
    '"a" ',
    "[1]\n",
    '"a\nb"',
    '"a"x"b"',
    "[1]x]",
    "[a]]",
    "[1]\n]",
    "\x00",
    " ",
]


def mutations(base: str) -> Iterator[str]:
    """Joiner placements, deletions, insertions and substitutions at every position."""
    yield base + JOINER
    yield JOINER + base
    yield base + " "
    yield " " + base
    for k in range(len(base)):
        yield base[:k] + JOINER + base[k:]
        yield base[:k] + base[k + 1 :]
        yield base[:k] + JOINER + base[k + 1 :]
        for junk in JUNK:
            yield base[:k] + junk + base[k:]
            yield base[:k] + junk + base[k + 1 :]
    yield base + base
    yield base + "," + base


def synthetic_inputs() -> set[str]:
    found: set[str] = set()
    for k in range(1, MAX_NESTING + 1):
        found.update(nested(k))
    found.update(BASES)
    for base in BASES:
        if len(base) <= MAX_FULL_ENDS_LENGTH:
            found.update(mutations(base))
    return found


def run_node(inputs: list[str]) -> dict[str, list[list[int]]]:
    """Run both ``*Ends`` functions on every input in one Node process."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH; the native JSON tests need Node.js")
    payload = {"inputs": inputs, "names": ENDS_FUNCTIONS}
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


def utf16_length(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def disagreements(leaf: str, inputs: list[str]) -> list[str]:
    """Inputs where the native ends and the Python fullmatch differ."""
    ends = run_node(inputs)[leaf]
    original = python_original(leaf)
    return [
        s
        for s, found in zip(inputs, ends, strict=True)
        if (utf16_length(s) in found) != (original.fullmatch(s) is not None)
    ]


def end_set_disagreements(inputs: list[str]) -> list[str]:
    """Block body only: ``j`` is an end iff ``fullmatch(s, 0, j)`` (no lookaround involved)."""
    short = [s for s in inputs if len(s) <= MAX_FULL_ENDS_LENGTH and s.isascii()]
    ends = run_node(short)[JSON_BLOCK]
    original = python_original(JSON_BLOCK)
    bad = []
    for s, found in zip(short, ends, strict=True):
        expected = [j for j in range(len(s) + 1) if original.fullmatch(s, 0, j)]
        if expected != found:
            bad.append(s)
    return bad


@pytest.fixture(scope="module")
def synthetic() -> list[str]:
    return sorted(synthetic_inputs())


@pytest.fixture(scope="module")
def corpus_inputs() -> dict[str, list[str]]:
    paths = sorted(FIXTURES.rglob("*.puml")) + [p for _, p, _ in enumerate_corpora()]
    json_lines, _ = collect_candidates(paths)
    return {JSON_BLOCK: sorted(json_lines), JSON_INVALID: sorted(json_lines)}


def report(label: str, leaf: str, inputs: list[str], started: float) -> None:
    hits = sum(1 for s in inputs if python_original(leaf).fullmatch(s))
    print(
        f"{label} {leaf}: {len(inputs)} inputs, {hits} match, {time.monotonic() - started:.1f}s",
        file=sys.stderr,
    )


def test_model_patterns_are_the_recursive_leaves():
    for leaf in ENDS_FUNCTIONS:
        assert "(?&jv)" in model_pattern(leaf)


@pytest.mark.parametrize("leaf", sorted(ENDS_FUNCTIONS))
def test_native_agrees_with_python_on_synthetic_inputs(leaf, synthetic):
    started = time.monotonic()
    assert disagreements(leaf, synthetic) == []
    report("synthetic", leaf, synthetic, started)


def test_block_body_end_sets_agree_with_python_endpos(synthetic):
    assert end_set_disagreements(synthetic) == []


def test_synthetic_inputs_cover_both_verdicts(synthetic):
    for leaf in ENDS_FUNCTIONS:
        verdicts = {python_original(leaf).fullmatch(s) is not None for s in synthetic}
        assert verdicts == {True, False}


@pytest.mark.corpus
@pytest.mark.parametrize("leaf", sorted(ENDS_FUNCTIONS))
def test_native_agrees_with_python_on_the_corpus(leaf, corpus_inputs):
    started = time.monotonic()
    inputs = corpus_inputs[leaf]
    assert disagreements(leaf, inputs) == []
    report("corpus", leaf, inputs, started)
