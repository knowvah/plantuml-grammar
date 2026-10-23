"""Pure parity logic: compare verdicts, build I6 reports, merge classifications, judge D5.

Definitions (D5: correctness is parity with the jar), per block, oracle versus interpreter:

* ``fr``  false reject: oracle accepted, interpreter rejected (or errored).
* ``fa``  false accept: oracle rejected, interpreter accepted.
* ``timeout``: the interpreter timed out; such a block is neither FR nor FA.
* ``diagram_mismatch`` (additive): both accepted but the interpreter's DiagramType
  differs from the oracle's; informational.
* ``raw_fr`` (additive): oracle accepted, the L0+L1 raw run rejected; informational.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from tools.interp import STATUS_TIMEOUT, Verdict
from tools.report.families import UNCLASSIFIED

KIND_FR = "fr"
KIND_FA = "fa"
KIND_TIMEOUT = "timeout"
KIND_DIAGRAM = "diagram_mismatch"
KIND_RAW_FR = "raw_fr"
COUNTED_KINDS = (KIND_FR, KIND_FA, KIND_TIMEOUT)
EXTRA_KINDS = (KIND_DIAGRAM, KIND_RAW_FR)
TOTAL_KEYS = ("blocks", "oracle_accepted", *COUNTED_KINDS, *EXTRA_KINDS)
GATING_KINDS = (KIND_FR, KIND_FA)
FR_CORPORA_ZERO = ("vega", "plantuml-ts")
PDIFF = "pdiff"
PDIFF_MAX_FR_RATE = 0.02
CLASS_BUG = "bug"
CLASS_SEMANTIC = "semantic"
CLASSES = (CLASS_BUG, CLASS_SEMANTIC, UNCLASSIFIED)
CASE_KEY = "{path}#{block}"
CORPUS_KEY = "{corpus}:{path}#{block}"

Case = dict[str, Any]
Totals = dict[str, int]


@dataclass(frozen=True)
class BlockResult:
    """Everything known about one block after the interpreter ran."""

    path: str  # relative to the corpus root
    block: int
    oracle: bool
    oracle_type: str | None
    interp: Verdict
    raw: Verdict | None = None


def _oracle_kind(result: BlockResult) -> list[str]:
    accepted = result.interp["accepted"]
    if result.oracle and not accepted:
        return [KIND_FR]
    if not result.oracle and accepted:
        return [KIND_FA]
    return []


def _extra_kinds(result: BlockResult) -> list[str]:
    kinds: list[str] = []
    if result.oracle and _differs(result.oracle_type, result.interp["diagram"]):
        kinds.append(KIND_DIAGRAM)
    if result.oracle and result.raw is not None and not _raw_ok(result.raw):
        kinds.append(KIND_RAW_FR)
    return kinds


def kinds_of(result: BlockResult) -> list[str]:
    """The ordered discrepancy kinds of one block (empty when the engines agree)."""
    if result.interp["status"] == STATUS_TIMEOUT:
        return [KIND_TIMEOUT]
    return _oracle_kind(result) + _extra_kinds(result)


def _differs(oracle_type: str | None, diagram: str | None) -> bool:
    return diagram is not None and oracle_type is not None and diagram != oracle_type


def _raw_ok(raw: Verdict) -> bool:
    return raw["accepted"] or raw["status"] == STATUS_TIMEOUT


def make_case(
    result: BlockResult, kind: str, classes: Mapping[str, Mapping[str, str]], corpus: str
) -> Case:
    """One I6 case; ``class``/``note`` come from the classification file, else unclassified."""
    entry = lookup_classification(classes, corpus, result.path, result.block)
    failure = result.interp["first_failure"]
    return {
        "path": result.path,
        "block": result.block,
        "oracle": result.oracle,
        "interp": result.interp["accepted"],
        "kind": kind,
        "class": entry.get("class", UNCLASSIFIED),
        "note": entry.get("note", ""),
        "oracle_type": result.oracle_type,
        "interp_diagram": result.interp["diagram"],
        "status": result.interp["status"],
        "first_failure": dict(failure) if failure else None,
    }


def lookup_classification(
    classes: Mapping[str, Mapping[str, str]], corpus: str, path: str, block: int
) -> Mapping[str, str]:
    """Classification for ``path#block``; the ``corpus:path#block`` key wins when present."""
    keys = (
        CORPUS_KEY.format(corpus=corpus, path=path, block=block),
        CASE_KEY.format(path=path, block=block),
    )
    return next((classes[k] for k in keys if k in classes), {})


def build_cases(
    results: Iterable[BlockResult], classes: Mapping[str, Mapping[str, str]], corpus: str
) -> list[Case]:
    """Cases for every discrepancy, ordered by (path, block, kind order)."""
    cases = [make_case(r, kind, classes, corpus) for r in results for kind in kinds_of(r)]
    return sorted(cases, key=lambda c: (c["path"], c["block"]))


def count_totals(results: Iterable[BlockResult]) -> Totals:
    """Block-level totals; a block counts once per discrepancy kind."""
    totals: Totals = dict.fromkeys(TOTAL_KEYS, 0)
    for result in results:
        totals["blocks"] += 1
        totals["oracle_accepted"] += int(result.oracle)
        for kind in kinds_of(result):
            totals[kind] += 1
    return totals


def build_report(
    pin: str,
    corpus: str,
    family: str,
    results: list[BlockResult],
    classes: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    """Contract I6 for one (corpus, family) slice."""
    return {
        "pin": pin,
        "corpus": corpus,
        "family": family,
        "totals": count_totals(results),
        "cases": build_cases(results, classes, corpus),
    }


def unclassified_gating(report: Mapping[str, Any]) -> int:
    """FR/FA cases of the report that have no ``bug``/``semantic`` classification."""
    return sum(
        1
        for case in report["cases"]
        if case["kind"] in GATING_KINDS and case["class"] not in (CLASS_BUG, CLASS_SEMANTIC)
    )


def fr_rate(totals: Mapping[str, int]) -> float:
    """FR over oracle-accepted blocks (0.0 when there are none)."""
    accepted = totals["oracle_accepted"]
    return totals[KIND_FR] / accepted if accepted else 0.0


def target_failures(report: Mapping[str, Any]) -> list[str]:
    """D5 targets the slice misses (empty list = met)."""
    totals, corpus = report["totals"], report["corpus"]
    problems: list[str] = []
    if corpus in FR_CORPORA_ZERO and totals[KIND_FR] > 0:
        problems.append(f"{corpus}: {totals[KIND_FR]} false reject(s), target 0")
    if corpus == PDIFF:
        if fr_rate(totals) > PDIFF_MAX_FR_RATE:
            problems.append(f"pdiff: FR rate {fr_rate(totals):.2%} exceeds {PDIFF_MAX_FR_RATE:.0%}")
        missing = unclassified_gating(report)
        if missing:
            problems.append(f"pdiff: {missing} unclassified FR/FA case(s)")
    return problems


def merge_reports(
    corpus: str, reports: list[dict[str, Any]], overlays: tuple[str, ...]
) -> dict[str, Any]:
    """Combine family slices into one corpus report; overlay families do not add to totals."""
    reports = sorted(reports, key=lambda r: r["family"])
    totals: Totals = dict.fromkeys(TOTAL_KEYS, 0)
    cases: list[Case] = []
    families: dict[str, dict[str, Any]] = {}
    for rep in reports:
        families[rep["family"]] = {"totals": rep["totals"], "overlay": rep["family"] in overlays}
        if rep["family"] in overlays:
            continue
        for key in TOTAL_KEYS:
            totals[key] += rep["totals"].get(key, 0)
        cases.extend({**c, "family": rep["family"]} for c in rep["cases"])
    pins = {r["pin"] for r in reports}
    return {
        "pin": pins.pop() if len(pins) == 1 else sorted(pins),
        "corpus": corpus,
        "totals": totals,
        "families": families,
        "cases": cases,
    }
