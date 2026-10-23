"""Family table (tasks T16-T34) and the block-to-family decision for the parity harness.

A block's family is decided by the oracle ``diagram_type`` (``DIAGRAM_TYPE_FAMILY``).
Two types are ambiguous or absent, and are resolved as follows (documented here because
the reports depend on it):

* ``ACTIVITY`` is shared by the legacy and the new activity syntax. The interpreter's
  accepting model factory decides; when the interpreter rejects, the block text does
  (legacy markers ``(*)``, ``-->``, ``===`` bars) and defaults to ``activity3``.
* ``None`` (the oracle rejected the block): the interpreter's accepting model factory,
  else the ``@start`` keyword (``KEYWORD_FAMILY``), else ``unclassified``.

``common`` and ``style`` are overlay families: they own no diagram type. ``common``
selects every block, ``style`` every block containing a ``<style>`` section; the merged
corpus report excludes overlays from its totals so no block is counted twice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

UNCLASSIFIED = "unclassified"
ACTIVITY_TYPE = "ACTIVITY"
ACTIVITY3 = "activity3"
ACTIVITY_LEGACY = "activity-legacy"
COMMON = "common"
STYLE = "style"
OVERLAY_FAMILIES = (COMMON, STYLE)
STYLE_MARKER = re.compile(r"<style\b", re.IGNORECASE)
LEGACY_ACTIVITY_MARKER = re.compile(r"\(\*\)|-+>|^\s*={2,}", re.MULTILINE)


@dataclass(frozen=True)
class Family:
    """One family task: its id, owning task, upstream factories and oracle types."""

    id: str
    task: str
    factories: tuple[str, ...]
    diagram_types: tuple[str, ...] = ()


FAMILIES: tuple[Family, ...] = (
    Family(COMMON, "T16", ()),
    Family("sequence", "T17", ("SequenceDiagramFactory",), ("SEQUENCE",)),
    Family("class", "T18", ("ClassDiagramFactory",), ("CLASS", "OBJECT")),
    Family(
        "description",
        "T19",
        ("DescriptionDiagramFactory",),
        ("DESCRIPTION", "USECASE", "COMPONENT", "DEPLOYMENT"),
    ),
    Family("state", "T20", ("StateDiagramFactory",), ("STATE",)),
    Family(ACTIVITY3, "T21a/T21b", ("ActivityDiagramFactory3",)),
    Family(ACTIVITY_LEGACY, "T22", ("ActivityDiagramFactory",)),
    Family("timing", "T23", ("TimingDiagramFactory",), ("TIMING",)),
    Family("gantt", "T24/T25", ("GanttDiagramFactory",), ("GANTT",)),
    Family(
        "mindmap-wbs",
        "T26",
        ("MindMapDiagramFactory", "WBSDiagramFactory"),
        ("MINDMAP", "WBS"),
    ),
    Family(
        "nwdiag-packet", "T27", ("NwDiagramFactory", "PacketDiagramFactory"), ("NWDIAG", "PACKET")
    ),
    Family("salt", "T28", ("PSystemSaltFactory",), ("SALT",)),
    Family(
        "json",
        "T29",
        ("JsonDiagramFactory", "YamlDiagramFactory", "HclDiagramFactory"),
        ("JSON", "YAML", "HCL"),
    ),
    Family(
        "misc-charts",
        "T30",
        (
            "ChartDiagramFactory",
            "ChenEerDiagramFactory",
            "WireDiagramFactory",
            "BpmDiagramFactory",
            "FlowDiagramFactory",
        ),
        ("CHART", "CHEN_EER", "WIRE", "BPM", "FLOW"),
    ),
    Family(
        "board-files-git",
        "T31",
        ("BoardDiagramFactory", "FilesDiagramFactory", "GitDiagramFactory"),
        ("BOARD", "FILES", "GIT"),
    ),
    Family(
        "meta-diagrams",
        "T32",
        (
            "PSystemEbnfFactory",
            "PSystemRegexFactory",
            "PSystemDefinitionFactory",
            "PSystemCreoleFactory",
            "ListSpriteDiagramFactory",
        ),
        ("EBNF", "REGEX", "DEFINITION", "CREOLE", "SPRITES"),
    ),
    Family(
        STYLE,
        "T33",
        (),
    ),
    Family(
        "single-line",
        "T34",
        (
            "PSystemWelcomeFactory",
            "PSystemColorsFactory",
            "PSystemLicenseFactory",
            "PSystemVersionFactory",
            "PSystemDonorsFactory",
            "PSystemSkinparameterListFactory",
            "PSystemListFontsFactory",
            "PSystemListEmojiFactory",
            "PSystemOpenIconicFactory",
            "PSystemListOpenIconicFactory",
            "PSystemListArchimateSpritesFactory",
            "PSystemSudokuFactory",
            "PSystemEggFactory",
            "PSystemAppleTwoFactory",
            "PSystemRIPFactory",
            "PSystemPathFactory",
            "PSystemCharlieFactory",
            "PSystemDedicationFactory",
            "HelpFactory",
            "CrashDiagramFactory",
            "PSystemDitaaFactory",
            "PSystemDotFactory",
            "PSystemLatexFactory",
            "PSystemMathFactory",
        ),
        ("HELP", "CRASH", "DITAA", "DOT", "LATEX", "MATH"),
    ),
)

FAMILY_IDS: tuple[str, ...] = tuple(f.id for f in FAMILIES)
BLOCK_FAMILY_IDS: tuple[str, ...] = tuple(f.id for f in FAMILIES if f.id not in OVERLAY_FAMILIES)
DIAGRAM_TYPE_FAMILY: dict[str, str] = {t: f.id for f in FAMILIES for t in f.diagram_types}
FACTORY_FAMILY: dict[str, str] = {fac: f.id for f in FAMILIES for fac in f.factories}

# ``@start<keyword>`` (lower case, no ``@start``) for blocks neither oracle nor
# interpreter classified; ``uml`` is deliberately absent (it can be any diagram).
KEYWORD_FAMILY: dict[str, str] = {
    "mindmap": "mindmap-wbs",
    "wbs": "mindmap-wbs",
    "gantt": "gantt",
    "salt": "salt",
    "json": "json",
    "yaml": "json",
    "hcl": "json",
    "ebnf": "meta-diagrams",
    "regex": "meta-diagrams",
    "chart": "misc-charts",
    "chen": "misc-charts",
    "wire": "misc-charts",
    "bpm": "misc-charts",
    "flow": "misc-charts",
    "board": "board-files-git",
    "files": "board-files-git",
    "git": "board-files-git",
    "nwdiag": "nwdiag-packet",
    "packetdiag": "nwdiag-packet",
    "timing": "timing",
    "crash": "single-line",
    "dot": "single-line",
    "ditaa": "single-line",
    "math": "single-line",
    "latex": "single-line",
}
START_KEYWORD = re.compile(r"^\s*@start(\w+)", re.IGNORECASE)


def candidate_families(diagram_type: str | None) -> frozenset[str]:
    """Families a block with this oracle type can end up in (before the interpreter runs)."""
    if diagram_type is None:
        return frozenset(BLOCK_FAMILY_IDS) | {UNCLASSIFIED}
    if diagram_type == ACTIVITY_TYPE:
        return frozenset({ACTIVITY3, ACTIVITY_LEGACY})
    return frozenset({DIAGRAM_TYPE_FAMILY.get(diagram_type, UNCLASSIFIED)})


def _activity_family(model_factory: str | None, text: str) -> str:
    known = FACTORY_FAMILY.get(model_factory or "")
    if known in (ACTIVITY3, ACTIVITY_LEGACY):
        return known
    return ACTIVITY_LEGACY if LEGACY_ACTIVITY_MARKER.search(text) else ACTIVITY3


def family_of(diagram_type: str | None, model_factory: str | None, text: str) -> str:
    """The primary family of a block (see the module docstring for the rules)."""
    if diagram_type == ACTIVITY_TYPE:
        return _activity_family(model_factory, text)
    if diagram_type is not None:
        return DIAGRAM_TYPE_FAMILY.get(diagram_type, UNCLASSIFIED)
    if model_factory in FACTORY_FAMILY:
        return FACTORY_FAMILY[model_factory]
    found = START_KEYWORD.match(text)
    if found:
        return KEYWORD_FAMILY.get(found.group(1).lower(), UNCLASSIFIED)
    return UNCLASSIFIED


def in_family(family: str, block_family: str, text: str) -> bool:
    """Does a block with primary family ``block_family`` belong to the requested slice?"""
    if family == COMMON:
        return True
    if family == STYLE:
        return bool(STYLE_MARKER.search(text))
    return family == block_family
