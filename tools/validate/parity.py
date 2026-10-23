"""Parity harness CLI: oracle vs interpreter (L2, and L0+L1 raw), per family.

    python -m tools.validate.parity [--corpus vega|plantuml-ts|pdiff|all] [--family F]
        [--timeout S] [--workers N]
    python -m tools.validate.parity merge [--corpus ...]

A run writes ``reports/parity/<corpus>/<family>.json`` (contract I6, see
``parity_core`` for the FR/FA/timeout definitions); ``merge`` combines the slices
into ``reports/parity-<corpus>.json`` and ``.md``. Exit codes: 0 targets met, 1 a D5
target missed, 2 environment or usage error (missing jar or corpus).
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
    has_preproc,
    load_models,
    run_interp,
)

EXIT_OK = 0
EXIT_TARGETS = 1
EXIT_ENV = 2
MERGE_COMMAND = "merge"
ALL = "all"
DEFAULT_TIMEOUT_S = 10.0
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


def default_list(corpus: str) -> tuple[Path, list[Path]]:
    """Corpus root and its ``*.puml`` files, via ``tools.validate.corpus``."""
    cfg = resolve(os.environ, Path.home())
    root = corpora._root(cfg, corpus)  # noqa: SLF001 - no public accessor for the root
    return root, [path for _, path, _ in corpora.enumerate_corpora(cfg, [corpus])]


@dataclass(frozen=True)
class Deps:
    """Injectable seams: corpus listing, oracle and interpreter."""

    list_corpus: Callable[[str], tuple[Path, list[Path]]] = default_list
    oracle: Callable[[list[Path]], Mapping[str, Any]] = oracle_verdicts
    interp: InterpFn | None = None


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


def run_corpus(
    corpus: str, opts: Options, deps: Deps, factories: Mapping[str, str | None], raw: bool
) -> list[dict[str, Any]]:
    """Run one corpus and return the slices for the wanted families that have blocks."""
    root, paths = deps.list_corpus(corpus)
    verdicts = deps.oracle(paths)
    jobs, skipped = collect_jobs(root, dict(verdicts))
    for rel in skipped:
        print(f"parity: oracle could not judge {rel}", file=sys.stderr)
    families = wanted_families(opts.family)
    jobs = [j for j in jobs if needs_job(j, families)]
    config = RunConfig(opts.model_dir, opts.timeout_s, raw)
    outcomes = run_interp(jobs, config, opts.workers, deps.interp)
    assigned = assign_families(jobs, outcomes, factories)
    data = Computed(jobs, outcomes, assigned)
    reports = [family_report(corpus, f, data, opts) for f in families]
    return [r for r in reports if r["totals"]["blocks"] or opts.family]


def write_slices(opts: Options, reports: Sequence[dict[str, Any]]) -> None:
    """Persist every slice under ``opts.out_dir``."""
    for report in reports:
        write_json(slice_path(opts.out_dir, report["corpus"], report["family"]), report)


def format_line(report: Mapping[str, Any]) -> str:
    """One stdout line of totals for a slice."""
    t = report["totals"]
    return (
        f"{report['corpus']:<12} {report['family']:<16} blocks={t['blocks']} fr={t['fr']} "
        f"fa={t['fa']} timeout={t['timeout']}"
    )


def run(opts: Options, deps: Deps | None = None) -> int:
    """Run the harness for every requested corpus; exit code per the module docstring."""
    deps = deps or Deps()
    try:
        models = load_models(opts.model_dir)
        factories = {m.id: m.factory for m in models.values()}
        failures: list[str] = []
        started = time.monotonic()
        for corpus in opts.corpora:
            reports = run_corpus(corpus, opts, deps, factories, has_preproc(models))
            write_slices(opts, reports)
            for report in reports:
                print(format_line(report))
                failures += target_failures(report)
        print(f"parity: wall {time.monotonic() - started:.1f}s", file=sys.stderr)
    except (ConfigError, OracleError, ModelLoadError, FileNotFoundError) as err:
        print(f"parity: {err}", file=sys.stderr)
        return EXIT_ENV
    for problem in failures:
        print(f"TARGET MISSED: {problem}", file=sys.stderr)
    return EXIT_TARGETS if failures else EXIT_OK


def merge(corpus_names: Sequence[str], out_dir: Path, reports_dir: Path) -> int:
    """Build ``parity-<corpus>.json``/``.md`` from the slices; exit 1 if targets are missed."""
    failures: list[str] = []
    for corpus in corpus_names:
        slices = read_slices(out_dir, corpus)
        if not slices:
            print(f"parity: no slices for {corpus} in {out_dir}", file=sys.stderr)
            continue
        merged = merge_reports(corpus, slices, OVERLAY_FAMILIES)
        write_json(reports_dir / f"parity-{corpus}.json", merged)
        (reports_dir / f"parity-{corpus}.md").write_text(summary_markdown(merged), encoding="utf-8")
        failures += target_failures(merged)
    for problem in failures:
        print(f"TARGET MISSED: {problem}", file=sys.stderr)
    return EXIT_TARGETS if failures else EXIT_OK


def _corpus_names(value: str) -> tuple[str, ...]:
    return corpora.CORPORA if value == ALL else (value,)


def _parser(merge_mode: bool) -> argparse.ArgumentParser:
    prog = "python -m tools.validate.parity" + (f" {MERGE_COMMAND}" if merge_mode else "")
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument("--corpus", choices=(*corpora.CORPORA, ALL), default=ALL)
    parser.add_argument("--out", type=Path, default=PARITY_DIR, help="slice directory")
    if merge_mode:
        parser.add_argument("--reports", type=Path, default=REPORTS_DIR)
        return parser
    parser.add_argument("--family", choices=(*FAMILY_IDS, UNCLASSIFIED))
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--models", type=Path, default=MODEL_DIR)
    parser.add_argument("--classify", type=Path, default=CLASSIFY_DIR)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == [MERGE_COMMAND]:
        ns = _parser(True).parse_args(args[1:])
        return merge(_corpus_names(ns.corpus), ns.out, ns.reports)
    ns = _parser(False).parse_args(args)
    opts = Options(
        corpora=_corpus_names(ns.corpus),
        family=ns.family,
        timeout_s=ns.timeout,
        workers=ns.workers,
        model_dir=ns.models,
        out_dir=ns.out,
        classify_dir=ns.classify,
    )
    return run(opts)


if __name__ == "__main__":
    sys.exit(main())
