"""Parity harness CLI: oracle vs interpreter (L2, and L0+L1 raw), per family.

    python -m tools.validate.parity [--corpus vega|plantuml-ts|pdiff|all] [--family F]
        [--timeout S] [--workers N] [--engine py|ts|both]
    python -m tools.validate.parity merge [--corpus ...] [--engine py|ts|both]

A run writes ``reports/parity/<corpus>/<family>.json`` (contract I6, see
``parity_core`` for the FR/FA/timeout definitions); ``merge`` combines the slices
into ``reports/parity-<corpus>.json`` and ``.md``. Exit codes: 0 targets met, 1 a D5
target missed, 2 environment or usage error (missing jar, corpus, or Node for ``ts``).

``--engine ts`` judges with the TypeScript engine (``ts_engine``) and writes the slices under
``reports/parity-ts/`` and the merged ``reports/parity-<corpus>-ts.{json,md}``; ``both`` runs
both engines, writes both sets and ``reports/engine-equality-<corpus>.{json,md}``. The default
``py`` writes exactly what it always has.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.config import ConfigError, resolve
from tools.model import ModelLoadError
from tools.report.families import (
    BLOCK_FAMILY_IDS,
    FAMILY_IDS,
    OVERLAY_FAMILIES,
    UNCLASSIFIED,
    candidate_families,
    family_of,
    in_family,
)
from tools.validate import corpus as corpora
from tools.validate.oracle import OracleError, default_pin, oracle_verdicts
from tools.validate.parity_core import BlockResult, build_report, merge_reports, target_failures
from tools.validate.parity_io import (
    CLASSIFY_DIR,
    PARITY_DIR,
    REPORTS_DIR,
    load_classes,
    read_slices,
    slice_path,
    summary_markdown,
    write_json,
)
from tools.validate.parity_run import (
    InterpFn,
    Job,
    Outcome,
    RunConfig,
    collect_jobs,
    compare_outcomes,
    has_preproc,
    load_models,
    run_interp,
)
from tools.validate.ts_engine import TsEngineError, run_ts

EXIT_OK = 0
EXIT_TARGETS = 1
EXIT_ENV = 2
MERGE_COMMAND = "merge"
ALL = "all"
DEFAULT_TIMEOUT_S = 10.0
TsFn = Callable[[Sequence[Job], RunConfig, int], list[Outcome]]
ENGINE_PY = "py"
ENGINE_TS = "ts"
ENGINE_BOTH = "both"
ENGINE_CHOICES = (ENGINE_PY, ENGINE_TS, ENGINE_BOTH)
TS_SUFFIX = "-ts"
MODEL_DIR = Path(__file__).resolve().parents[2] / "model"


@dataclass(frozen=True)
class Options:
    """Parsed command line."""

    corpora: tuple[str, ...]
    family: str | None = None
    timeout_s: float = DEFAULT_TIMEOUT_S
    workers: int = 1
    model_dir: Path = MODEL_DIR
    out_dir: Path = PARITY_DIR
    classify_dir: Path = CLASSIFY_DIR
    engine: str = ENGINE_PY
    reports_dir: Path = REPORTS_DIR

    @property
    def engines(self) -> tuple[str, ...]:
        """The engines to run, in report order."""
        return (ENGINE_PY, ENGINE_TS) if self.engine == ENGINE_BOTH else (self.engine,)


def default_list(corpus: str) -> tuple[Path, list[Path]]:
    """Corpus root and its ``*.puml`` files, via ``tools.validate.corpus``."""
    cfg = resolve(os.environ, Path.home())
    root = corpora._root(cfg, corpus)  # noqa: SLF001 - no public accessor for the root
    return root, [path for _, path, _ in corpora.enumerate_corpora(cfg, [corpus])]


@dataclass(frozen=True)
class Deps:
    """Injectable seams: corpus listing, oracle, interpreter and TypeScript judge."""

    list_corpus: Callable[[str], tuple[Path, list[Path]]] = default_list
    oracle: Callable[[list[Path]], Mapping[str, Any]] = oracle_verdicts
    interp: InterpFn | None = None
    ts: TsFn | None = None


def engine_dir(out_dir: Path, engine: str) -> Path:
    """Slice directory of an engine: ``out_dir`` for py, a ``-ts`` sibling for ts."""
    return out_dir if engine == ENGINE_PY else out_dir.with_name(out_dir.name + TS_SUFFIX)


def report_stem(corpus: str, engine: str) -> str:
    """Merged report base name: ``parity-<corpus>`` plus ``-ts`` for the ts engine."""
    return f"parity-{corpus}" + ("" if engine == ENGINE_PY else TS_SUFFIX)


def wanted_families(family: str | None) -> tuple[str, ...]:
    """The requested slice, or every block family (overlays only when asked for)."""
    return (family,) if family else (*BLOCK_FAMILY_IDS, UNCLASSIFIED)


def needs_job(job: Job, families: Sequence[str]) -> bool:
    """Can this block land in a wanted family? (cheap pre-filter before the interpreter)"""
    possible = candidate_families(job.oracle_type)
    return any(f in OVERLAY_FAMILIES or f in possible for f in families)


def assign_families(
    jobs: Sequence[Job], outcomes: Sequence[Outcome], factories: Mapping[str, str | None]
) -> list[str]:
    """Primary family per job (see ``tools.report.families``)."""
    return [
        family_of(job.oracle_type, factories.get(interp["model"] or ""), job.text)
        for job, (interp, _raw) in zip(jobs, outcomes, strict=True)
    ]


@dataclass(frozen=True)
class Computed:
    """Jobs with their interpreter outcomes and primary families (parallel sequences)."""

    jobs: Sequence[Job]
    outcomes: Sequence[Outcome]
    assigned: Sequence[str]

    def members(self, family: str) -> list[int]:
        """Indices of the blocks belonging to the requested slice."""
        return [
            i for i, job in enumerate(self.jobs) if in_family(family, self.assigned[i], job.text)
        ]

    def result(self, i: int) -> BlockResult:
        """The combined result of block ``i``."""
        job, (interp, raw) = self.jobs[i], self.outcomes[i]
        return BlockResult(job.path, job.block, job.oracle, job.oracle_type, interp, raw)


def family_report(corpus: str, family: str, data: Computed, opts: Options) -> dict[str, Any]:
    """The I6 slice of one family from already-computed outcomes."""
    results = [data.result(i) for i in data.members(family)]
    classes = load_classes(family, opts.classify_dir)
    return build_report(default_pin(), corpus, family, results, classes)


@dataclass(frozen=True)
class CorpusRun:
    """Slices per engine, plus the py-vs-ts mismatch rows when both engines ran."""

    reports: Mapping[str, list[dict[str, Any]]]
    mismatches: list[Mapping[str, Any]] | None = None


def judge_jobs(
    engine: str, jobs: Sequence[Job], config: RunConfig, opts: Options, deps: Deps
) -> list[Outcome]:
    """Outcomes of one engine; wall time goes to stderr."""
    started = time.monotonic()
    if engine == ENGINE_TS:
        outcomes = (deps.ts or run_ts)(jobs, config, opts.workers)
    else:
        outcomes = run_interp(jobs, config, opts.workers, deps.interp)
    print(f"parity: {engine} engine wall {time.monotonic() - started:.1f}s", file=sys.stderr)
    return outcomes


def engine_slices(corpus: str, data: Computed, opts: Options) -> list[dict[str, Any]]:
    """The wanted family slices of one engine that have blocks (or were asked for)."""
    slices = [family_report(corpus, f, data, opts) for f in wanted_families(opts.family)]
    return [r for r in slices if r["totals"]["blocks"] or opts.family]


def run_corpus(
    corpus: str, opts: Options, deps: Deps, factories: Mapping[str, str | None], raw: bool
) -> CorpusRun:
    """Run one corpus on every requested engine; slices only for families that have blocks."""
    root, paths = deps.list_corpus(corpus)
    verdicts = deps.oracle(paths)
    jobs, skipped = collect_jobs(root, dict(verdicts))
    for rel in skipped:
        print(f"parity: oracle could not judge {rel}", file=sys.stderr)
    families = wanted_families(opts.family)
    jobs = [j for j in jobs if needs_job(j, families)]
    config = RunConfig(opts.model_dir, opts.timeout_s, raw)
    outcomes = {e: judge_jobs(e, jobs, config, opts, deps) for e in opts.engines}
    reports = {
        e: engine_slices(corpus, Computed(jobs, o, assign_families(jobs, o, factories)), opts)
        for e, o in outcomes.items()
    }
    rows = None
    if opts.engine == ENGINE_BOTH:
        rows = compare_outcomes(jobs, outcomes[ENGINE_PY], outcomes[ENGINE_TS])
    return CorpusRun(reports, rows)


def write_slices(opts: Options, reports: Sequence[dict[str, Any]], engine: str = ENGINE_PY) -> None:
    """Persist every slice under the engine's slice directory."""
    directory = engine_dir(opts.out_dir, engine)
    for report in reports:
        write_json(slice_path(directory, report["corpus"], report["family"]), report)


def equality_report(corpus: str, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The py-vs-ts equality document: mismatch count and one row per mismatched job."""
    return {"pin": default_pin(), "corpus": corpus, "mismatches": len(rows), "rows": list(rows)}


def equality_markdown(report: Mapping[str, Any]) -> str:
    """Summary line plus a table of the mismatched jobs and their differing fields."""
    lines = [
        f"# Engine equality: {report['corpus']}",
        "",
        f"Mismatches: {report['mismatches']}",
        "",
    ]
    if report["rows"]:
        lines += ["| job | field | py | ts |", "|---|---|---|---|"]
    for row in report["rows"]:
        job = f"`{row['path']}#{row['block']}`"
        for field in row["fields"]:
            left, right = row["left"][field], row["right"][field]
            lines.append(f"| {job} | {field} | `{left}` | `{right}` |")
    return "\n".join(lines) + "\n"


def write_equality(opts: Options, corpus: str, rows: Sequence[Mapping[str, Any]]) -> None:
    """Write ``engine-equality-<corpus>.{json,md}`` under ``opts.reports_dir``."""
    report = equality_report(corpus, rows)
    stem = opts.reports_dir / f"engine-equality-{corpus}"
    write_json(stem.with_suffix(".json"), report)
    stem.with_suffix(".md").write_text(equality_markdown(report), encoding="utf-8")


def format_line(report: Mapping[str, Any]) -> str:
    """One stdout line of totals for a slice."""
    t = report["totals"]
    return (
        f"{report['corpus']:<12} {report['family']:<16} blocks={t['blocks']} fr={t['fr']} "
        f"fa={t['fa']} timeout={t['timeout']}"
    )


def emit(opts: Options, corpus: str, outcome: CorpusRun) -> list[str]:
    """Write, print and judge one corpus run; returns the missed targets."""
    failures: list[str] = []
    for engine, reports in outcome.reports.items():
        write_slices(opts, reports, engine)
        for report in reports:
            print(format_line(report) + ("" if engine == ENGINE_PY else f" [{engine}]"))
            failures += target_failures(report)
    if outcome.mismatches is not None:
        write_equality(opts, corpus, outcome.mismatches)
        print(f"parity: {corpus} engine equality mismatches={len(outcome.mismatches)}")
    return failures


def run(opts: Options, deps: Deps | None = None) -> int:
    """Run the harness for every requested corpus; exit code per the module docstring."""
    deps = deps or Deps()
    try:
        models = load_models(opts.model_dir)
        factories = {m.id: m.factory for m in models.values()}
        failures: list[str] = []
        started = time.monotonic()
        for corpus in opts.corpora:
            outcome = run_corpus(corpus, opts, deps, factories, has_preproc(models))
            failures += emit(opts, corpus, outcome)
        print(f"parity: wall {time.monotonic() - started:.1f}s", file=sys.stderr)
    except (ConfigError, OracleError, ModelLoadError, TsEngineError, FileNotFoundError) as err:
        print(f"parity: {err}", file=sys.stderr)
        return EXIT_ENV
    for problem in failures:
        print(f"TARGET MISSED: {problem}", file=sys.stderr)
    return EXIT_TARGETS if failures else EXIT_OK


def merge(
    corpus_names: Sequence[str], out_dir: Path, reports_dir: Path, engine: str = ENGINE_PY
) -> int:
    """Build ``parity-<corpus>[-ts].json``/``.md`` from the slices; exit 1 on a missed target."""
    failures: list[str] = []
    engines = (ENGINE_PY, ENGINE_TS) if engine == ENGINE_BOTH else (engine,)
    for corpus in corpus_names:
        for each in engines:
            failures += _merge_one(corpus, engine_dir(out_dir, each), reports_dir, each)
    for problem in failures:
        print(f"TARGET MISSED: {problem}", file=sys.stderr)
    return EXIT_TARGETS if failures else EXIT_OK


def _merge_one(corpus: str, slice_dir: Path, reports_dir: Path, engine: str) -> list[str]:
    slices = read_slices(slice_dir, corpus)
    if not slices:
        print(f"parity: no slices for {corpus} in {slice_dir}", file=sys.stderr)
        return []
    merged = merge_reports(corpus, slices, OVERLAY_FAMILIES)
    stem = reports_dir / report_stem(corpus, engine)
    write_json(stem.with_suffix(".json"), merged)
    stem.with_suffix(".md").write_text(summary_markdown(merged), encoding="utf-8")
    return target_failures(merged)


def _corpus_names(value: str) -> tuple[str, ...]:
    return corpora.CORPORA if value == ALL else (value,)


def _parser(merge_mode: bool) -> argparse.ArgumentParser:
    prog = "python -m tools.validate.parity" + (f" {MERGE_COMMAND}" if merge_mode else "")
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument("--corpus", choices=(*corpora.CORPORA, ALL), default=ALL)
    parser.add_argument("--out", type=Path, default=PARITY_DIR, help="slice directory")
    parser.add_argument("--engine", choices=ENGINE_CHOICES, default=ENGINE_PY)
    if merge_mode:
        parser.add_argument("--reports", type=Path, default=REPORTS_DIR)
        return parser
    parser.add_argument("--family", choices=(*FAMILY_IDS, UNCLASSIFIED))
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--models", type=Path, default=MODEL_DIR)
    parser.add_argument("--classify", type=Path, default=CLASSIFY_DIR)
    parser.add_argument("--reports", type=Path, default=REPORTS_DIR, help="equality report dir")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == [MERGE_COMMAND]:
        ns = _parser(True).parse_args(args[1:])
        return merge(_corpus_names(ns.corpus), ns.out, ns.reports, ns.engine)
    ns = _parser(False).parse_args(args)
    opts = Options(
        corpora=_corpus_names(ns.corpus),
        family=ns.family,
        timeout_s=ns.timeout,
        workers=ns.workers,
        model_dir=ns.models,
        out_dir=ns.out,
        classify_dir=ns.classify,
        engine=ns.engine,
        reports_dir=ns.reports,
    )
    return run(opts)


if __name__ == "__main__":
    sys.exit(main())
