"""Choosing and ordering candidate diagram models for a block.

Upstream (``PSystemBuilder.java:258-282``) walks its factory list (``:133-200``) in
order and skips factories whose ``DiagramType`` is not among
``DiagramType.findStartTypes(first line)`` (``core/DiagramType.java:69-92``, table
``:94-218``). The document layer's ``start_map`` (``model/document.yaml``) states that
composition directly: start keyword -> factories in ``PSystemBuilder`` order. Per
factory the **top** model is used (``tools.model.resolve.top_models``), so a
hand-written family model that includes a generated one replaces it.

Keyword lookup mirrors ``findStartTypes``: the keyword after ``@start`` is matched by
prefix (``@startumlfoo`` is ``uml``, ``DiagramType.java:220-232``). A keyword no entry
covers is ``PSystemUnsupported`` (``error/PSystemErrorUtils.java:58-59`` for an unknown
word, ``PSystemBuilder.java:283-284`` when no factory has the type): ``plan`` returns
``None`` for it.

Source of the map, in priority order: an explicit ``start_map`` argument (entries may
name factories or model ids), the first ``layer: document`` model carrying one, else
the legacy fallback below (models filtered by ``diagram`` and ordered by the first
factory of each type).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from tools.model import ResolvedModel, ResolvedModels
from tools.model.resolve import top_models

DIAGRAM_LAYER = "diagram"
DOCUMENT_LAYER = "document"
START_PREFIX = "@start"
UML_TYPES = frozenset(
    "SEQUENCE STATE CLASS OBJECT ACTIVITY DESCRIPTION COMPOSITE TIMING HELP SPRITES".split()
)
START_TYPES: dict[str, frozenset[str]] = {
    "bpm": frozenset({"BPM"}),
    "board": frozenset({"BOARD"}),
    "chart": frozenset({"CHART"}),
    "creole": frozenset({"CREOLE"}),
    "chronology": frozenset({"CHRONOLOGY"}),
    "chen": frozenset({"CHEN_EER"}),
    "crash": frozenset({"CRASH"}),
    "dot": frozenset({"DOT"}),
    "ditaa": frozenset({"DITAA"}),
    "def": frozenset({"DEFINITION"}),
    "ebnf": frozenset({"EBNF"}),
    "flow": frozenset({"FLOW"}),
    "files": frozenset({"FILES"}),
    "gantt": frozenset({"GANTT"}),
    "project": frozenset({"GANTT"}),
    "git": frozenset({"GIT"}),
    "hcl": frozenset({"HCL"}),
    "jcckit": frozenset({"JCCKIT"}),
    "json": frozenset({"JSON"}),
    "latex": frozenset({"LATEX"}),
    "math": frozenset({"MATH"}),
    "mindmap": frozenset({"MINDMAP"}),
    "nwdiag": frozenset({"NWDIAG"}),
    "packetdiag": frozenset({"PACKET"}),
    "regex": frozenset({"REGEX"}),
    "salt": frozenset({"SALT"}),
    "sprites": frozenset({"SPRITES"}),
    "uml": UML_TYPES,
    "wire": frozenset({"WIRE"}),
    "wbs": frozenset({"WBS"}),
    "yaml": frozenset({"YAML"}),
}
# DiagramType of each factory in PSystemBuilder.java:133-200, first occurrence only.
FACTORY_TYPE_ORDER = (
    "SEQUENCE CLASS ACTIVITY DESCRIPTION STATE BPM SALT DOT NWDIAG MINDMAP WBS CHART "
    "PACKET DITAA DEFINITION SPRITES MATH LATEX CREOLE GANTT FLOW TIMING HELP WIRE JSON "
    "GIT FILES BOARD YAML HCL EBNF REGEX CHEN_EER CRASH"
).split()
ORDER_INDEX = {name: n for n, name in enumerate(FACTORY_TYPE_ORDER)}

StartMap = Mapping[str, Sequence[str]]


def start_types(keyword: str) -> frozenset[str]:
    """``DiagramType.findStartTypes`` as a prefix lookup; empty when unknown."""
    for prefix, types in START_TYPES.items():
        if keyword.startswith(prefix):
            return types
    return frozenset()


def lookup(start_map: StartMap, keyword: str) -> Sequence[str] | None:
    """Names mapped to ``keyword``: exact key, ``@start`` + key, then a prefix key."""
    for key in (keyword, START_PREFIX + keyword):
        if key in start_map:
            return start_map[key]
    for key, names in start_map.items():
        bare = key.removeprefix(START_PREFIX)
        if bare and keyword.startswith(bare):
            return names
    return None


def document_start_map(models: ResolvedModels) -> StartMap | None:
    """The ``start_map`` of the first document-layer model that has one."""
    for model in models.values():
        if model.layer == DOCUMENT_LAYER and model.start_map:
            return model.start_map
    return None


def _diagram_models(models: ResolvedModels) -> list[ResolvedModel]:
    return [m for m in models.values() if m.layer == DIAGRAM_LAYER]


class Dispatcher:
    """Candidate diagram models per start keyword for one ``models`` mapping."""

    def __init__(self, models: ResolvedModels, start_map: StartMap | None = None) -> None:
        self._models = models
        self._map = start_map if start_map is not None else document_start_map(models)
        self._tops = top_models(models) if self._map is not None else {}

    def plan(self, keyword: str | None) -> list[ResolvedModel] | None:
        """Models to try in order; ``None`` means ``PSystemUnsupported``.

        ``keyword`` is ``None`` for a bare body (every diagram model is tried).
        """
        if keyword is None:
            return _diagram_models(self._models)
        if self._map is None:
            return self._by_type(keyword)
        names = lookup(self._map, keyword)
        if names is None:
            return None
        picked = (self._pick(name) for name in names)
        return [m for m in picked if m is not None]

    def _pick(self, name: str) -> ResolvedModel | None:
        if name in self._tops:
            return self._models[self._tops[name]]
        model = self._models.get(name)
        return model if model is not None and model.layer == DIAGRAM_LAYER else None

    def _by_type(self, keyword: str) -> list[ResolvedModel] | None:
        types = start_types(keyword)
        if not types:
            return None
        chosen = [m for m in _diagram_models(self._models) if m.diagram in types]
        return sorted(chosen, key=lambda m: ORDER_INDEX.get(m.diagram or "", len(ORDER_INDEX)))


def candidates(
    models: ResolvedModels, keyword: str | None, start_map: StartMap | None
) -> list[ResolvedModel]:
    """Diagram models to try, in order (``[]`` when unsupported)."""
    return Dispatcher(models, start_map).plan(keyword) or []
