"""Test prefix patterns against every JOINER-boundary prefix of long texts, in one Node process.

A ``scan_join`` chain tests ``text_1, text_2, ...`` where each text extends the previous one,
so one long text plus the lengths (UTF-16 code units) of its prefixes carries the whole
chain. Node slices the prefixes itself; nothing is sent twice. A sample whose ``test`` throws
(V8 raises ``RangeError`` when backtracking exhausts the stack) yields ``None`` instead of
aborting the batch, so the sweep can count those separately.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.model.node_regex import DEFAULT_FLAGS, SKIP_REASON

NODE_TIMEOUT_S = 3600
NODE_SCRIPT = """
const fs = require("fs");
const jobs = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const out = jobs.map(({source, flags, chains}) => {
  let re;
  try { re = new RegExp(source, flags); } catch (e) { return null; }
  return chains.map(({text, offsets}) => offsets.map((o) => {
    try { return re.test(text.slice(0, o)); } catch (e) { return null; }
  }));
});
process.stdout.write(JSON.stringify(out));
"""


@dataclass(frozen=True)
class Chain:
    """``text`` and the UTF-16 lengths of the prefixes to test."""

    text: str
    offsets: Sequence[int]


@dataclass(frozen=True)
class ChainJob:
    """One pattern with the chains to run it on."""

    source: str
    chains: Sequence[Chain]
    flags: str = DEFAULT_FLAGS


def run_chains(jobs: Sequence[ChainJob]) -> list[list[list[bool | None]] | None]:
    """Per job: per chain, per offset ``True`` / ``False`` / ``None`` (threw); ``None`` job =
    the pattern did not compile. Skips the test when Node is missing."""
    node = shutil.which("node")
    if node is None:
        pytest.skip(SKIP_REASON)
    payload = [
        {
            "source": j.source,
            "flags": j.flags,
            "chains": [{"text": c.text, "offsets": list(c.offsets)} for c in j.chains],
        }
        for j in jobs
    ]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "jobs.json"
        path.write_text(json.dumps(payload), encoding="utf-8", errors="surrogatepass")
        done = subprocess.run(  # noqa: S603 - fixed argv, trusted local file
            [node, "-e", NODE_SCRIPT, str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=NODE_TIMEOUT_S,
        )
    if done.returncode != 0:
        raise RuntimeError(f"node exited with {done.returncode}: {done.stderr[:2000]}")
    result: list[list[list[bool | None]] | None] = json.loads(done.stdout)
    return result
