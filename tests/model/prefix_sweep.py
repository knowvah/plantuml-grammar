"""Sweep the Python interpreter's ``scan_join`` against the Node prefix patterns.

For every join and every block body index ``i``, ``scan_join`` is run with a
``Deadline`` that records the successive ``joined + JOINER`` texts passed to ``prefix`` and
Python's partial-match verdict for each. Those texts extend one another, so a chain is stored
as its longest text plus the prefix lengths; Node slices every one of them (no text is
skipped) and the verdicts are compared: Python true and Node false is a violation (the prefix
pattern must be a superset), Node true and Python false is slack, a throw is counted.

``sweep_parallel`` splits the files into chunks and sweeps them in worker processes; each
worker records and judges its own chunk, so the checked texts do not depend on the pool.
"""

from __future__ import annotations

import os
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tests.model.prefix_node import Chain, ChainJob, run_chains
from tools.interp.compile import compile_part
from tools.interp.scan import BlockTimeout, Deadline, Join, scan_join
from tools.interp.source import Line, split_block, split_blocks
from tools.model import Part

BLOCK_BUDGET_S = 120.0
FLUSH_CHARS = 4_000_000  # buffered chain text before a Node call
MEMO_CHARS = 1_500  # verdicts of texts up to this length are memoized per file chunk
MEMO_MAX = 200_000
SHARD_MIN_LINES = 2_000
GIANT_BYTES = 60_000  # files at least this big are split by start index
CHUNK_FILES = 8  # small, and biggest files first, so no worker is left with a long tail
UTF16 = "utf-16-le"
UTF16_UNIT_BYTES = 2
VIOLATION_CONTEXT = 200


@dataclass(frozen=True)
class JoinSpec:
    """A distinct (Part, line cap, gluing) join, its command names and its prefix pattern."""

    part: Part
    max_lines: int
    glue: bool
    commands: tuple[str, ...]
    pattern: str

    @property
    def label(self) -> str:
        return ",".join(sorted(self.commands))


@dataclass
class Sweep:
    """Superset violations, slack, throws and counts, per command label."""

    violations: list[tuple[str, str]] = field(default_factory=list)
    slack: Counter[str] = field(default_factory=Counter)
    accepted_by_python: Counter[str] = field(default_factory=Counter)
    threw: Counter[str] = field(default_factory=Counter)
    texts: int = 0
    chains: int = 0
    bodies: int = 0
    timeouts: int = 0

    def merge(self, other: Sweep) -> None:
        self.violations.extend(other.violations)
        self.slack.update(other.slack)
        self.accepted_by_python.update(other.accepted_by_python)
        self.threw.update(other.threw)
        self.texts += other.texts
        self.chains += other.chains
        self.bodies += other.bodies
        self.timeouts += other.timeouts


class _ChainRecorder(Deadline):
    """A Deadline that records the texts passed to ``prefix`` as one growing chain."""

    def __init__(self, memo: dict[tuple[int, str], bool], spec_index: int) -> None:
        super().__init__(BLOCK_BUDGET_S)
        self.memo, self.spec_index = memo, spec_index
        self.text = ""
        self.offsets: list[int] = []
        self.verdicts: list[bool] = []

    def prefix(self, pattern: Any, text: str) -> bool:
        key = (self.spec_index, text)
        short = len(text) <= MEMO_CHARS
        verdict = self.memo.get(key) if short else None
        if verdict is None:
            verdict = super().prefix(pattern, text)
            if short and len(self.memo) < MEMO_MAX:
                self.memo[key] = verdict
        self.extend(text, verdict)
        return verdict

    def extend(self, text: str, verdict: bool) -> None:
        if not self.offsets:
            delta, base = text, 0
        elif text.startswith(self.text):
            delta, base = text[len(self.text) :], self.offsets[-1]
        else:  # scan_join only ever extends; a break would make the chain unsound
            raise AssertionError("prefix texts of one scan_join call must extend each other")
        units = len(delta.encode(UTF16, "surrogatepass")) // UTF16_UNIT_BYTES
        self.text = text
        self.offsets.append(base + units)
        self.verdicts.append(verdict)


def _bodies(paths: Iterable[Path]) -> Iterator[list[Line]]:
    seen: set[tuple[tuple[str, str], ...]] = set()
    for path in paths:
        for block in split_blocks(path.read_text(encoding="utf-8", errors="replace")):
            lines = split_block(block).body
            key = tuple((line.text, line.trimmed) for line in lines)
            if key not in seen:
                seen.add(key)
                yield lines


@dataclass
class _Buffer:
    """Chains waiting for a Node call, per spec index, deduplicated by their longest text."""

    chains: dict[int, dict[str, tuple[Chain, list[bool]]]] = field(default_factory=dict)
    chars: int = 0

    def add(self, spec_index: int, rec: _ChainRecorder) -> None:
        per_spec = self.chains.setdefault(spec_index, {})
        if rec.text not in per_spec:
            per_spec[rec.text] = (Chain(rec.text, rec.offsets), rec.verdicts)
            self.chars += len(rec.text)


def _judge(specs: Sequence[JoinSpec], buffer: _Buffer, sweep: Sweep) -> None:
    indexes = sorted(buffer.chains)
    jobs = [ChainJob(specs[i].pattern, [c for c, _ in buffer.chains[i].values()]) for i in indexes]
    for index, job, outcome in zip(indexes, jobs, run_chains(jobs), strict=True):
        spec = specs[index]
        assert outcome is not None, f"{spec.label}: prefix pattern does not compile"
        verdicts = [v for _, v in buffer.chains[index].values()]
        for chain, python, results in zip(job.chains, verdicts, outcome, strict=True):
            _compare(spec.label, chain, python, results, sweep)
    buffer.chains.clear()
    buffer.chars = 0


def _compare(
    label: str, chain: Chain, python: list[bool], results: list[bool | None], sweep: Sweep
) -> None:
    sweep.chains += 1
    for offset, py, node in zip(chain.offsets, python, results, strict=True):
        sweep.texts += 1
        sweep.accepted_by_python[label] += py
        if node is None:  # the engine threw: the scanner must treat that as "keep going"
            sweep.threw[label] += 1
        elif py and not node:
            context = chain.text.encode(UTF16, "surrogatepass")[: offset * UTF16_UNIT_BYTES]
            sweep.violations.append(
                (label, context[-VIOLATION_CONTEXT * UTF16_UNIT_BYTES :].decode(UTF16, "replace"))
            )
        else:
            sweep.slack[label] += bool(node) and not py


@dataclass
class _State:
    """What one sweeping process carries between bodies."""

    buffer: _Buffer
    sweep: Sweep
    flush: Callable[[], None]
    memo: dict[tuple[int, str], bool] = field(default_factory=dict)


def _sweep_body(joins: Sequence[Join], lines: list[Line], starts: range, state: _State) -> None:
    memo, buffer, sweep = state.memo, state.buffer, state.sweep
    for index, join in enumerate(joins):
        for i in starts:
            rec = _ChainRecorder(memo, index)
            try:
                scan_join(join, lines, i, rec)
            except BlockTimeout:
                sweep.timeouts += 1
            if rec.offsets:
                buffer.add(index, rec)
        if buffer.chars >= FLUSH_CHARS:
            state.flush()


def sweep_paths(
    specs: Sequence[JoinSpec], paths: Sequence[Path], shard: tuple[int, int] = (0, 1)
) -> Sweep:
    """Record and judge every join over every body of ``paths``, in this process.

    ``shard=(r, k)`` runs only the start indexes ``i`` with ``i % k == r`` of the bodies longer
    than ``SHARD_MIN_LINES`` (and the shorter bodies only when ``r == 0``), so ``k`` workers
    can split one huge body between them.
    """
    r, k = shard
    joins = [Join(compile_part(s.part), s.max_lines, s.glue) for s in specs]
    sweep, buffer = Sweep(), _Buffer()
    state = _State(buffer, sweep, lambda: _judge(specs, buffer, sweep))
    for lines in _bodies(paths):
        big = len(lines) > SHARD_MIN_LINES
        if r and not big:
            continue
        sweep.bodies += not r
        starts = range(r, len(lines), k) if big else range(len(lines))
        _sweep_body(joins, lines, starts, state)
    if buffer.chains:
        _judge(specs, buffer, sweep)
    return sweep


_SPECS: list[JoinSpec] = []


def _init_worker(specs: list[JoinSpec]) -> None:
    _SPECS[:] = specs


def _sweep_chunk(paths: list[Path], shard: tuple[int, int]) -> Sweep:
    return sweep_paths(_SPECS, paths, shard)


def _plan_tasks(paths: Sequence[Path], count: int) -> list[tuple[list[Path], tuple[int, int]]]:
    """Big files are split by start index over every worker; the rest go in small chunks."""
    giants = [p for p in paths if p.stat().st_size >= GIANT_BYTES]
    rest = sorted(set(paths) - set(giants), key=lambda p: (-p.stat().st_size, str(p)))
    tasks = [(giants, (r, count * 2)) for r in range(count * 2)] if giants else []
    return tasks + [(rest[i : i + CHUNK_FILES], (0, 1)) for i in range(0, len(rest), CHUNK_FILES)]


def sweep_parallel(
    name: str, specs: list[JoinSpec], paths: Sequence[Path], workers: int | None = None
) -> Sweep:
    """``sweep_paths`` over the ``_plan_tasks`` tasks in a process pool."""
    count = workers or os.cpu_count() or 1
    tasks = _plan_tasks(paths, count)
    total, started = Sweep(), time.monotonic()
    pool = ProcessPoolExecutor(max_workers=count, initializer=_init_worker, initargs=(specs,))
    with pool:
        futures = [pool.submit(_sweep_chunk, *task) for task in tasks]
        for done, future in enumerate(as_completed(futures), 1):
            total.merge(future.result())
            print(
                f"[{name}] {done}/{len(tasks)} tasks, {time.monotonic() - started:.0f}s",
                file=sys.stderr,
            )
    return total
