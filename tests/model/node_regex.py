"""Compile and run JavaScript regexes in Node, one process per batch.

``run_batch`` writes the jobs to a temporary JSON file, runs ``node -e`` once, and returns
``[compiles, matches]`` per job, in order. ``matches`` has one boolean per sample (``test``
of the compiled ``RegExp``; anchor the source yourself for full-match semantics) and is
empty when the source does not compile.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import pytest

NODE_TIMEOUT_S = 300
DEFAULT_FLAGS = "u"
SKIP_REASON = "node is not on PATH; the JS regex tests need Node.js"
NODE_SCRIPT = """
const fs = require("fs");
const jobs = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const out = jobs.map(({source, flags, samples}) => {
  let re;
  try { re = new RegExp(source, flags); } catch (e) { return [false, []]; }
  return [true, samples.map((s) => re.test(s))];
});
process.stdout.write(JSON.stringify(out));
"""


@dataclass(frozen=True)
class Job:
    """One regex source with the strings to test it against."""

    source: str
    samples: Sequence[str] = ()
    flags: str = DEFAULT_FLAGS


class Outcome(NamedTuple):
    """``[compiles, matches]`` for one job."""

    compiles: bool
    matches: list[bool]


def run_batch(jobs: Sequence[Job]) -> list[Outcome]:
    """Run every job in a single Node process; skips the test when Node is missing."""
    node = shutil.which("node")
    if node is None:
        pytest.skip(SKIP_REASON)
    payload = [{"source": j.source, "flags": j.flags, "samples": list(j.samples)} for j in jobs]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "jobs.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        done = subprocess.run(  # noqa: S603 - fixed argv, trusted local file
            [node, "-e", NODE_SCRIPT, str(path)],
            capture_output=True,
            text=True,
            check=True,
            timeout=NODE_TIMEOUT_S,
        )
    return [Outcome(compiles, matches) for compiles, matches in json.loads(done.stdout)]


def compiles_all(sources: Sequence[str], flags: str = DEFAULT_FLAGS) -> list[bool]:
    """Does each source compile as ``new RegExp(source, flags)``?"""
    return [o.compiles for o in run_batch([Job(s, (), flags) for s in sources])]
