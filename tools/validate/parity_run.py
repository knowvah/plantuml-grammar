"""Run the interpreter over corpus blocks: job collection and the interpreter pool.

 ``run_interp`` fans the jobs over a
process pool (each worker resolves the models once) and returns outcomes in job order, so
reports are deterministic. Every engine is injectable for tests.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.interp import STATUS_ERROR, Verdict, accepts
from tools.interp.source import split_blocks
from tools.model import ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve
from tools.validate.oracle import BlockVerdict

PREPROC_LAYER = "preproc"
POOL_CHUNK = 32
Outcome = tuple[Verdict, Verdict | None]
InterpFn = Callable[["Job"], Outcome]
VERDICT_FIELDS = ("accepted", "diagram", "first_failure", "model", "status")
LAYER_L2 = "l2"
LAYER_RAW = "raw"


@dataclass(frozen=True)
class Job:
    """One block to judge: ``text`` is the L2 input, ``raw_text`` the L0+L1 input."""

    path: str  # relative to the corpus root
    block: int
    text: str
    raw_text: str | None
    oracle: bool
    oracle_type: str | None


@dataclass(frozen=True)
class RunConfig:
    """What a worker needs to build its interpreter."""

    model_dir: Path
    timeout_s: float
    use_raw: bool


def error_verdict(message: str) -> Verdict:
    """A verdict for an engine crash, with the message in ``first_failure.text``."""
    return {
        "accepted": False,
        "diagram": None,
        "first_failure": {"line": 0, "text": message},
        "model": None,
        "status": STATUS_ERROR,
    }


def load_models(model_dir: Path) -> ResolvedModels:
    """Load and resolve a model tree once."""
    return resolve(load_dir(model_dir))


def has_preproc(models: ResolvedModels) -> bool:
    """Is a preproc-layer (L0+L1) model present?"""
    return any(m.layer == PREPROC_LAYER for m in models.values())


def _split_raw(text: str, expected: int) -> list[str | None]:
    blocks = split_blocks(text)
    return list(blocks) if len(blocks) == expected else [None] * expected


def collect_jobs(
    root: Path,
    verdicts: dict[str, list[BlockVerdict]],
    read: Callable[[Path], str] = lambda p: p.read_text(encoding="utf-8", errors="replace"),
) -> tuple[list[Job], list[str]]:
    """Jobs for every oracle-judged block, plus the files the oracle could not judge.

    The L2 text is the oracle's preprocessed block (raw text if it is empty); the raw
    text is the block as ``split_blocks`` finds it, used only when the count matches.
    """
    jobs: list[Job] = []
    skipped: list[str] = []
    for key in sorted(verdicts):
        blocks = verdicts[key]
        rel = str(Path(key).relative_to(root))
        if any("error" in b for b in blocks):
            skipped.append(rel)
            continue
        raws = _split_raw(read(Path(key)), len(blocks))
        for block, raw in zip(blocks, raws, strict=True):
            text = "\n".join(block["preproc"]) or raw or ""
            jobs.append(
                Job(
                    rel,
                    block["index"],
                    text,
                    raw,
                    block["accepted"],
                    block["diagram_type"],
                )
            )
    return jobs, skipped


_WORKER: dict[str, object] = {}


def _init_worker(config: RunConfig) -> None:
    _WORKER["models"] = load_models(config.model_dir)
    _WORKER["config"] = config


def run_job(job: Job) -> Outcome:
    """Judge one job with the worker's models (the default ``InterpFn``)."""
    models: ResolvedModels = _WORKER["models"]  # type: ignore[assignment]
    config: RunConfig = _WORKER["config"]  # type: ignore[assignment]
    return judge(models, job, config)


def judge(models: ResolvedModels, job: Job, config: RunConfig) -> Outcome:
    """Run L2 (and L0+L1 when enabled and the raw block is known) on one job."""
    try:
        l2 = accepts(models, job.text, timeout_s=config.timeout_s)
    except Exception as exc:  # noqa: BLE001 - one bad block must not abort a corpus run
        return error_verdict(f"{type(exc).__name__}: {exc}"), None
    if not (config.use_raw and job.raw_text is not None):
        return l2, None
    return l2, _raw_verdict(models, job.raw_text, config.timeout_s)


def _raw_verdict(models: ResolvedModels, raw_text: str, timeout_s: float) -> Verdict | None:
    try:
        return accepts(models, raw_text, raw=True, timeout_s=timeout_s)
    except Exception as exc:  # noqa: BLE001
        return error_verdict(f"{type(exc).__name__}: {exc}")


def run_interp(
    jobs: Sequence[Job], config: RunConfig, workers: int = 1, fn: InterpFn | None = None
) -> list[Outcome]:
    """Outcomes in job order. ``fn`` (tests) forces in-process execution."""
    if fn is not None:
        return [fn(job) for job in jobs]
    if workers <= 1 or len(jobs) <= POOL_CHUNK:
        _init_worker(config)
        return [run_job(job) for job in jobs]
    with ProcessPoolExecutor(
        max_workers=workers, initializer=_init_worker, initargs=(config,)
    ) as pool:
        return list(pool.map(run_job, jobs, chunksize=POOL_CHUNK))


def _verdict_diff(layer: str, a: Verdict | None, b: Verdict | None) -> list[str]:
    if a is None or b is None:
        return [] if a is b else [layer]
    return [f"{layer}.{f}" for f in VERDICT_FIELDS if a.get(f) != b.get(f)]  # type: ignore[misc]


def _field_value(outcome: Outcome, field: str) -> Any:
    layer, _, key = field.partition(".")
    verdict = outcome[0] if layer == LAYER_L2 else outcome[1]
    if verdict is None:
        return None
    return verdict.get(key) if key else verdict  # type: ignore[misc]


def compare_outcomes(
    jobs: Sequence[Job], left: Sequence[Outcome], right: Sequence[Outcome]
) -> list[Mapping[str, Any]]:
    """One row per job whose two engines disagree, naming the differing fields.

    A field is ``<l2|raw>.<verdict key>``; a bare ``raw`` means only one engine produced a
    raw verdict. Rows keep job order and carry the differing values as ``left``/``right``.
    """
    rows: list[Mapping[str, Any]] = []
    for job, (l2a, rawa), (l2b, rawb) in zip(jobs, left, right, strict=True):
        fields = _verdict_diff(LAYER_L2, l2a, l2b) + _verdict_diff(LAYER_RAW, rawa, rawb)
        if fields:
            rows.append(
                {
                    "path": job.path,
                    "block": job.block,
                    "fields": fields,
                    "left": {f: _field_value((l2a, rawa), f) for f in fields},
                    "right": {f: _field_value((l2b, rawb), f) for f in fields},
                }
            )
    return rows
