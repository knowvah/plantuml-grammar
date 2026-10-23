"""Coverage matrix: every extracted command per diagram factory, and whether a model rule
carries its provenance class.

    python -m tools.report.coverage [--out docs/coverage.md]

Status per command (``extracted/<Factory>.json`` entries, ``commands`` plus
``unreachable``):

* ``modeled``   the factory's resolved model has at least as many rules whose
  ``provenance.class`` equals the command class as the extraction has commands of it;
* ``partial``   fewer rules than commands of that class, or the matching rule is opaque;
* ``excluded(reason)``  no rule, and ``reports/classify/*.yaml`` ``exclusions:`` names the
  class (full name or simple name) with a reason;
* ``missing``   none of the above.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tools.model import ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve, top_models
from tools.report.families import FACTORY_FAMILY, UNCLASSIFIED

REPO_ROOT = Path(__file__).resolve().parents[2]
EXTRACTED_DIR = REPO_ROOT / "extracted"
MODEL_DIR = REPO_ROOT / "model"
CLASSIFY_DIR = REPO_ROOT / "reports" / "classify"
DEFAULT_OUT = REPO_ROOT / "docs" / "coverage.md"
EXCLUSIONS_KEY = "exclusions"
REASON_KEY = "reason"
KIND_OPAQUE = "opaque"
MODELED, PARTIAL, MISSING, EXCLUDED = "modeled", "partial", "missing", "excluded"
STATUSES = (MODELED, PARTIAL, MISSING, EXCLUDED)
NO_FACTORY = "(none)"


@dataclass(frozen=True)
class Command:
    """One extracted command (or unreachable placeholder) and its coverage status."""

    order: int
    cls: str
    kind: str
    status: str
    note: str = ""

    @property
    def simple(self) -> str:
        return self.cls.rsplit(".", 1)[-1]


def load_exclusions(directory: Path = CLASSIFY_DIR) -> dict[str, str]:
    """``class -> reason`` from every ``exclusions:`` mapping in the classify files."""
    found: dict[str, str] = {}
    for path in sorted(directory.glob("*.yaml")) if directory.is_dir() else []:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries = doc.get(EXCLUSIONS_KEY) if isinstance(doc, dict) else None
        for name, value in (entries or {}).items():
            reason = value.get(REASON_KEY, "") if isinstance(value, dict) else value
            found[str(name)] = str(reason)
    return found


def rules_of(models: ResolvedModels, model_id: str) -> Counter[str]:
    """Count rules per provenance class in the resolved top model of a factory."""
    counts: Counter[str] = Counter()
    for entries in models[model_id].contexts.values():
        for entry in entries:
            if isinstance(entry, dict) and "provenance" in entry:
                kind = ("opaque:" if entry.get("kind") == KIND_OPAQUE else "") + str(
                    entry["provenance"]["class"]
                )
                counts[kind] += 1
    return counts


def _status(
    cls: str, wanted: int, modeled: Counter[str], excluded: Mapping[str, str]
) -> tuple[str, str]:
    plain, opaque = modeled[cls], modeled[f"opaque:{cls}"]
    if plain + opaque >= wanted and not opaque:
        return MODELED, ""
    if plain + opaque:
        return PARTIAL, ""
    simple = cls.rsplit(".", 1)[-1]
    reason = excluded.get(cls) or excluded.get(simple)
    return (EXCLUDED, reason) if reason else (MISSING, "")


def classify_commands(
    doc: Mapping[str, Any], modeled: Counter[str], excluded: Mapping[str, str]
) -> list[Command]:
    """Status of every command of one extracted factory document, in upstream order."""
    entries: list[tuple[int, str, str, str]] = [
        (c["order"], c["class"], c["kind"], "") for c in doc["commands"]
    ] + [(u["order"], u["class"], "unreachable", u["reason"]) for u in doc["unreachable"]]
    wanted = Counter(cls for _, cls, _, _ in entries)
    commands = []
    for order, cls, kind, note in sorted(entries):
        status, reason = _status(cls, wanted[cls], modeled, excluded)
        commands.append(Command(order, cls, kind, status, reason or note))
    return commands


def build_matrix(
    extracted: Mapping[str, Mapping[str, Any]],
    models: ResolvedModels,
    excluded: Mapping[str, str],
) -> dict[str, list[Command]]:
    """``factory -> commands`` for every extracted factory (no model: all missing)."""
    tops = top_models(models)
    matrix: dict[str, list[Command]] = {}
    for factory, doc in sorted(extracted.items()):
        modeled = rules_of(models, tops[factory]) if factory in tops else Counter()
        matrix[factory] = classify_commands(doc, modeled, excluded)
    return matrix


def load_extracted(directory: Path = EXTRACTED_DIR) -> dict[str, dict[str, Any]]:
    """Every ``extracted/<Factory>.json`` carrying a ``factory`` (gantt-lang has none)."""
    docs = (json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.json")))
    return {d["factory"]: d for d in docs if d.get("factory")}


def _count(commands: Iterable[Command]) -> Counter[str]:
    return Counter(c.status for c in commands)


def _label(c: Command) -> str:
    """Status, with the reason for ``excluded`` and ``partial`` commands."""
    return f"{c.status} ({c.note})" if c.note and c.status in (EXCLUDED, PARTIAL) else c.status


def render(matrix: Mapping[str, Sequence[Command]], diagrams: Mapping[str, str]) -> str:
    """Markdown: summary per factory, then one command table per factory."""
    lines = ["# Command coverage", "", "Generated by `python -m tools.report.coverage`.", ""]
    lines += ["| factory | diagram | family | " + " | ".join(STATUSES) + " |"]
    lines += ["|" + "---|" * (3 + len(STATUSES))]
    for factory, commands in matrix.items():
        n = _count(commands)
        family = FACTORY_FAMILY.get(factory, UNCLASSIFIED)
        cells = " | ".join(str(n[s]) for s in STATUSES)
        lines.append(f"| {factory} | {diagrams.get(factory, '')} | {family} | {cells} |")
    for factory, commands in matrix.items():
        lines += ["", f"## {factory}", "", "| # | command | kind | status |", "|---|---|---|---|"]
        lines += [f"| {c.order} | {c.simple} | {c.kind} | {_label(c)} |" for c in commands]
    return "\n".join(lines) + "\n"


def generate(
    extracted_dir: Path = EXTRACTED_DIR,
    model_dir: Path = MODEL_DIR,
    classify_dir: Path = CLASSIFY_DIR,
) -> str:
    """The full Markdown report from the repository's current state."""
    extracted = load_extracted(extracted_dir)
    models = resolve(load_dir(model_dir))
    matrix = build_matrix(extracted, models, load_exclusions(classify_dir))
    diagrams = {f: str(d.get("diagramType", "")) for f, d in extracted.items()}
    return render(matrix, diagrams)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; writes ``docs/coverage.md``."""
    parser = argparse.ArgumentParser(prog="python -m tools.report.coverage")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(generate(), encoding="utf-8")
    print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
