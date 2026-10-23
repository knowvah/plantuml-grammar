"""Semantic-gap report: every false accept classified ``semantic``, grouped by kind.

    python -m tools.report.semantic_gaps [--reports DIR] [--classify DIR] [--out FILE]
        [--check-cites]

A false accept (FA) is a block the jar rejects and the model interpreter accepts. The
``semantic`` ones are checks upstream performs while it executes commands (name lookups,
duplicate names, state left behind by earlier lines) that a regular grammar over single
lines cannot express. The report joins the merged parity reports
(``reports/parity-<corpus>.json``, written by ``tools.validate.parity merge``) with the
classification files (``reports/classify/<family>.yaml``, which carry the upstream
``cite`` for each case) and groups the cases by the kind of check, found by keyword rules
over the classification note (``KIND_RULES``, first match wins).

``--check-cites`` verifies that every cite resolves at the pinned upstream sha (the file
exists there and the line range lies inside it).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tools.translate.provenance import ProvenanceError, git_reader
from tools.validate.parity_core import CLASS_SEMANTIC, KIND_FA, lookup_classification

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = REPO_ROOT / "reports"
CLASSIFY_DIR = REPORTS_DIR / "classify"
DEFAULT_OUT = REPO_ROOT / "docs" / "semantic-gaps.md"
CORPORA = ("vega", "plantuml-ts", "pdiff")
JAVA_PREFIX = "src/main/java/"
PACKAGE_PREFIX = "net/sourceforge/plantuml/"
CITE_PATTERN = re.compile(r"^(?P<path>.+\.java):(?P<first>\d+)(?:-(?P<last>\d+))?$")
EXIT_OK, EXIT_UNRESOLVED = 0, 1

KIND_REFERENCE = "Reference resolution"
KIND_DUPLICATE = "Duplicate declarations"
KIND_CONTEXT = "Context-dependent and cross-line checks"
KIND_STATE = "Entity and sequence state"
KIND_PREPROC = "Preprocessor errors"
KIND_OTHER = "Other"
KIND_ORDER = (KIND_REFERENCE, KIND_DUPLICATE, KIND_CONTEXT, KIND_STATE, KIND_PREPROC, KIND_OTHER)

KIND_DESCRIPTIONS = {
    KIND_REFERENCE: "A command names something (an entity, player, task, label, colour, sprite) "
    "that no earlier command declared, or that a lookup cannot resolve.",
    KIND_DUPLICATE: "A command declares a name that is already taken, or a name clashes with "
    "another kind of entity (a class named like a package).",
    KIND_CONTEXT: "The block is valid line by line, and a check over the whole body (tree depth, "
    "single root, date span) fails.",
    KIND_STATE: "Earlier lines leave state (a pending `create`, a delay, a package hierarchy, a "
    "concurrent region) that makes a later, well-formed line fail.",
    KIND_PREPROC: "The preprocessor fails (a built-in called with the wrong arity).",
    KIND_OTHER: "Not matched by a keyword rule; see the per-case note.",
}

# Ordered (kind, pattern) rules over the lower-cased classification note; first match wins.
KIND_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (KIND_PREPROC, re.compile(r"preprocessor")),
    (
        KIND_STATE,
        re.compile(
            r"pendingcreate|lastdelay|not a package|bad hierarchy|made \S+ a package"
            r"|concurrent region"
        ),
    ),
    (KIND_DUPLICATE, re.compile(r"twice|already|reuses|bad name")),
    (
        KIND_REFERENCE,
        re.compile(
            r"unknown|undeclared|undefined|never declared|declared on a later line"
            r"|does not exist|no class|not known|no such|names no|lookup|link endpoint"
        ),
    ),
    (KIND_CONTEXT, re.compile(r"cross-line|20-year|final check|second root|level \d")),
)

OTHER_COLUMNS = ("timeout", "diagram_mismatch", "raw_fr")
OTHER_HEADERS = ("Interpreter timeouts", "Diagram mismatches", "Raw-mode FR")

# Findings for the latest measurement (reports/parity-*.json as of that run). They explain the
# non-gating columns of the table above; rerun the parity harness before trusting the numbers.
OTHER_NOTES = """
These counts do not gate the release (the D5 gates are FR and FA).

**Interpreter timeouts.** A block the interpreter does not finish within the harness budget
(10 s) counts as neither FR nor FA.

**Diagram mismatches (82).** Both sides accept; the interpreter names a different diagram
type than the jar. 65 are `CLASS` in the jar and `SEQUENCE` in the model, 8 `ACTIVITY` vs
`SEQUENCE`: a sequence body with no participant is incomplete
(`sequencediagram/SequenceDiagram.java:591-593`, `PSystemCommandFactory.java:161-162`), so
the jar moves on to a later factory, while the model accepts it as a sequence diagram. 4
`HELP` vs `SPRITES` (`klimt/sprite/ListSpriteDiagram.java:60`), 2 `BPM` vs `CRASH`
(`crash/CrashDiagram.java:58`), 1 `DESCRIPTION` vs `CLASS`. Accept/reject agrees.

**Raw-mode FR (381).** The interpreter in raw mode (`accepts(..., raw=True)`, the L0+L1
surface model of the preprocessor, run on the unpreprocessed block) rejects blocks the jar
accepts. This is informational: the gating run uses the jar's preprocessed text. Causes
measured earlier: unexpanded `name(...)` call lines, `!assert`, `!final` redefinitions and
missing includes, which need a real preprocessor. See `.agent-notes/T14.md`.
"""


@dataclass(frozen=True)
class Gap:
    """One semantic false accept."""

    corpus: str
    family: str
    path: str
    block: int
    kind: str
    cite: str
    note: str


Reader = Callable[[str], str]


def gap_kind(note: str) -> str:
    """The kind of check a classification note describes."""
    lowered = note.lower()
    return next((kind for kind, rule in KIND_RULES if rule.search(lowered)), KIND_OTHER)


def short_cite(cite: str) -> str:
    """``src/main/java/net/sourceforge/plantuml/a/B.java:1`` as ``a/B.java:1`` (display only)."""
    return cite.removeprefix(JAVA_PREFIX).removeprefix(PACKAGE_PREFIX)


def load_reports(directory: Path, corpora: Sequence[str] = CORPORA) -> dict[str, dict[str, Any]]:
    """Merged parity reports by corpus; corpora without a file are skipped."""
    found: dict[str, dict[str, Any]] = {}
    for corpus in corpora:
        path = directory / f"parity-{corpus}.json"
        if path.exists():
            found[corpus] = json.loads(path.read_text(encoding="utf-8"))
    return found


def load_classes(directory: Path) -> dict[str, dict[str, dict[str, str]]]:
    """``family -> {[corpus:]path#block -> entry}`` from every classification file."""
    classes: dict[str, dict[str, dict[str, str]]] = {}
    for path in sorted(directory.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries = doc.get("cases") if isinstance(doc, dict) else None
        if entries:
            classes[path.stem] = {str(k): dict(v) for k, v in entries.items()}
    return classes


def collect(
    reports: Mapping[str, Mapping[str, Any]],
    classes: Mapping[str, Mapping[str, Mapping[str, str]]],
) -> list[Gap]:
    """Every FA case classified semantic, with its note and cite from the family file."""
    gaps: list[Gap] = []
    for corpus, report in reports.items():
        for case in report["cases"]:
            if case["kind"] != KIND_FA or case["class"] != CLASS_SEMANTIC:
                continue
            entry = lookup_classification(
                classes.get(case["family"], {}), corpus, case["path"], case["block"]
            )
            note = entry.get("note", "")
            gaps.append(
                Gap(
                    corpus,
                    case["family"],
                    case["path"],
                    case["block"],
                    gap_kind(note),
                    entry.get("cite", ""),
                    note,
                )
            )
    return gaps


def unresolved_cites(gaps: Sequence[Gap], reader: Reader) -> list[str]:
    """Cites that do not resolve through ``reader`` (a path -> text reader at the pin)."""
    bad: list[str] = []
    for cite in dict.fromkeys(g.cite for g in gaps):
        found = CITE_PATTERN.match(cite)
        if not found or not _line_exists(found, reader):
            bad.append(cite)
    return bad


def _line_exists(found: re.Match[str], reader: Reader) -> bool:
    try:
        text = reader(found["path"])
    except ProvenanceError:
        return False
    last = int(found["last"] or found["first"])
    return 1 <= int(found["first"]) <= last <= len(text.splitlines())


def _counts(gaps: Sequence[Gap]) -> dict[str, Counter[str]]:
    by_family: dict[str, Counter[str]] = defaultdict(Counter)
    for g in gaps:
        by_family[g.family][g.corpus] += 1
    return dict(sorted(by_family.items()))


def _family_table(gaps: Sequence[Gap]) -> list[str]:
    lines = ["| family | " + " | ".join(CORPORA) + " | total |", "|---|---|---|---|---|"]
    for family, counter in _counts(gaps).items():
        cells = [str(counter[c]) for c in CORPORA]
        lines.append(f"| {family} | {' | '.join(cells)} | {sum(counter.values())} |")
    return lines


def _cite_table(gaps: Sequence[Gap]) -> list[str]:
    first_note: dict[str, str] = {}
    for g in gaps:
        first_note.setdefault(g.cite, g.note)
    counts = Counter(g.cite for g in gaps)
    lines = ["| upstream check (at 97a5992) | cases | example |", "|---|---|---|"]
    for cite, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        shown = f"`{short_cite(cite)}`" if cite else "(no cite)"
        lines.append(f"| {shown} | {count} | {first_note[cite].replace('|', '/')} |")
    return lines


def _kind_section(kind: str, gaps: Sequence[Gap]) -> list[str]:
    return [
        "",
        f"## {kind}",
        "",
        KIND_DESCRIPTIONS[kind],
        "",
        *_family_table(gaps),
        "",
        *_cite_table(gaps),
    ]


def _other_section(totals: Mapping[str, Mapping[str, int]]) -> list[str]:
    lines = ["", "## Other parity differences (not false accepts)", ""]
    lines += [
        "| corpus | " + " | ".join(OTHER_HEADERS) + " |",
        "|---" * (len(OTHER_HEADERS) + 1) + "|",
    ]
    for corpus in CORPORA:
        if corpus in totals:
            cells = [str(totals[corpus].get(key, 0)) for key in OTHER_COLUMNS]
            lines.append(f"| {corpus} | {' | '.join(cells)} |")
    return [*lines, "", *OTHER_NOTES.strip().splitlines()]


def render(gaps: Sequence[Gap], totals: Mapping[str, Mapping[str, int]]) -> str:
    """The Markdown report."""
    per_corpus = Counter(g.corpus for g in gaps)
    split = ", ".join(f"{c} {per_corpus[c]}" for c in CORPORA)
    lines = [
        "# Semantic gaps",
        "",
        "Generated by `python -m tools.report.semantic_gaps` from `reports/parity-*.json` and "
        "`reports/classify/*.yaml`.",
        "",
        "A semantic gap is a block that the jar rejects and the model accepts (a false accept), "
        "because upstream rejects it while *executing* commands, using state or lookups that a "
        "grammar over single lines cannot express. Each group below cites the upstream check at "
        "pin 97a5992.",
        "",
        f"Total: {len(gaps)} false accepts ({split}).",
    ]
    for kind in KIND_ORDER:
        members = [g for g in gaps if g.kind == kind]
        if members:
            lines += _kind_section(kind, members)
    lines += _other_section(totals)
    return "\n".join(lines) + "\n"


def _totals(reports: Mapping[str, Mapping[str, Any]]) -> dict[str, Mapping[str, int]]:
    return {corpus: report.get("totals", {}) for corpus, report in reports.items()}


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; writes ``docs/semantic-gaps.md``."""
    parser = argparse.ArgumentParser(prog="python -m tools.report.semantic_gaps")
    parser.add_argument("--reports", type=Path, default=REPORTS_DIR)
    parser.add_argument("--classify", type=Path, default=CLASSIFY_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check-cites", action="store_true")
    args = parser.parse_args(argv)
    reports = load_reports(args.reports)
    gaps = collect(reports, load_classes(args.classify))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(gaps, _totals(reports)), encoding="utf-8")
    print(f"wrote {args.out}", file=sys.stderr)
    if args.check_cites:
        bad = unresolved_cites(gaps, git_reader())
        for cite in bad:
            print(f"unresolved cite: {cite or '(empty)'}", file=sys.stderr)
        return EXIT_UNRESOLVED if bad else EXIT_OK
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
