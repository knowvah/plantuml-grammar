"""Parity report files: classification input, slice and merged JSON, summary Markdown.

Classification file ``reports/classify/<family>.yaml`` (written by family tasks)::

    cases:
      "sequence/foo.puml#0": {class: semantic, note: "...", upstream: "File.java:12"}
      "vega:sequence/foo.puml#1": {class: bug, note: "..."}   # corpus-scoped key
    exclusions:                                                # read by tools.report.coverage
      CommandFoo: "reason"

Paths are relative to the corpus root. A flat file whose keys all contain ``#`` is also
accepted. Entries that are not mappings are ignored.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from tools.validate.parity_core import COUNTED_KINDS, EXTRA_KINDS, fr_rate

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = REPO_ROOT / "reports"
PARITY_DIR = REPORTS_DIR / "parity"
CLASSIFY_DIR = REPORTS_DIR / "classify"
CASES_KEY = "cases"
CASE_MARKER = "#"
SUMMARY_COLUMNS = ("family", "blocks", *COUNTED_KINDS, *EXTRA_KINDS, "FR rate")
INDENT = 2


def _case_entries(doc: Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(doc.get(CASES_KEY), dict):
        return doc[CASES_KEY]  # type: ignore[no-any-return]
    return {k: v for k, v in doc.items() if CASE_MARKER in str(k)}


def load_classes(family: str, directory: Path = CLASSIFY_DIR) -> dict[str, dict[str, str]]:
    """Classifications keyed by ``[corpus:]path#block``; empty when the file is absent."""
    path = directory / f"{family}.yaml"
    if not path.exists():
        return {}
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = _case_entries(doc) if isinstance(doc, dict) else {}
    return {
        str(key): {k: str(v) for k, v in value.items()}
        for key, value in entries.items()
        if isinstance(value, dict)
    }


def slice_path(out_dir: Path, corpus: str, family: str) -> Path:
    """Where the slice for ``(corpus, family)`` lives."""
    return out_dir / corpus / f"{family}.json"


def write_json(path: Path, doc: Mapping[str, Any]) -> None:
    """Write sorted-key, stable JSON (creating parent directories)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=INDENT, sort_keys=True) + "\n", encoding="utf-8")


def read_slices(out_dir: Path, corpus: str) -> list[dict[str, Any]]:
    """All family slices of a corpus, sorted by file name."""
    folder = out_dir / corpus
    if not folder.is_dir():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))]


def _row(label: str, totals: Mapping[str, int]) -> str:
    cells = [label, str(totals["blocks"])]
    cells += [str(totals[k]) for k in (*COUNTED_KINDS, *EXTRA_KINDS)]
    cells.append(f"{fr_rate(totals):.2%}")
    return "| " + " | ".join(cells) + " |"


def _case_line(case: Mapping[str, Any]) -> str:
    note = f" - {case['note']}" if case["note"] else ""
    where = f"`{case['path']}#{case['block']}`"
    return f"- {case['family']}: {where} {case['kind']} ({case['class']}){note}"


def summary_markdown(merged: Mapping[str, Any]) -> str:
    """Totals per family (overlays marked) plus every classified or unclassified case."""
    header = "| " + " | ".join(SUMMARY_COLUMNS) + " |"
    rule = "|" + "---|" * len(SUMMARY_COLUMNS)
    lines = [f"# Parity: {merged['corpus']}", "", f"Pin: `{merged['pin']}`", "", header, rule]
    for family, info in merged["families"].items():
        label = f"{family} (overlay)" if info["overlay"] else family
        lines.append(_row(label, info["totals"]))
    lines.append(_row("**total**", merged["totals"]))
    lines += ["", "## Cases", ""]
    interesting = [c for c in merged["cases"] if c["kind"] in COUNTED_KINDS]
    lines += [_case_line(c) for c in interesting] or ["none"]
    return "\n".join(lines) + "\n"
