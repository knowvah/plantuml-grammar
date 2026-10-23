"""L0 document layer (``model/document.yaml``) and the embedded non-command models.

Every fixture under ``tests/fixtures/document`` has a ``.json`` sibling with the jar's
per-block verdicts (``accepted`` and, when accepted, the oracle's ``diagram_type``).
The interpreter runs each file the way upstream does: ``split_blocks`` (BlockUmlBuilder)
then ``accepts(..., raw=True)`` per block. ``diagram`` is compared only where the oracle
reports one: it is ``null`` for diagrams that are not a ``TitledDiagram``
(``tools/oracle/Oracle.java``), e.g. license, math, dot.

The ``single-line`` group is run with ``start_map`` restricted to the single-line
factories (PSystemBuilder order) so it checks the embedded models themselves: the
generated ``@startuml`` families accept some bare words the jar rejects (a T06/T07 model
gap), and the jar's ``null`` diagram type there shows a single-line factory won.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.interp import accepts
from tools.interp.compile import compile_part
from tools.interp.source import split_blocks
from tools.model import ResolvedModel, ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve, top_models

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO / "model"
EXTRACTED = REPO / "extracted"
FIXTURES = REPO / "tests" / "fixtures" / "document"
PUML = sorted(FIXTURES.rglob("*.puml"))
DOCUMENT_ID = "document"
EMBEDDED_PREFIX = "embedded-"
OPAQUE_REASON = "opaque-no-regex-field"
SINGLE_LINE_GROUP = "single-line"
# PSystemBuilder.java:144-186 order, single-line (SEQUENCE) factories only.
SINGLE_LINE_FACTORIES = [
    "PSystemLicenseFactory",
    "PSystemVersionFactory",
    "PSystemDonorsFactory",
    "PSystemSkinparameterListFactory",
    "PSystemListFontsFactory",
    "PSystemListEmojiFactory",
    "PSystemOpenIconicFactory",
    "PSystemListOpenIconicFactory",
    "PSystemListArchimateSpritesFactory",
    "PSystemEggFactory",
    "PSystemAppleTwoFactory",
    "PSystemRIPFactory",
    "PSystemCharlieFactory",
    "PSystemDedicationFactory",
]
# syntax/LanguageDescriptor.java:56-85.
DIRECTIVE_PAIRS = (
    "board bpm chart chen chronology creole def ditaa dot ebnf files flow gantt git hcl "
    "jcckit json latex math mindmap nwdiag project regex salt sprites uml wbs wire yaml "
    "packetdiag"
).split()
D4_OPAQUE = ("dot", "ditaa", "math", "latex", "yaml", "hcl")
NO_FACTORY_KEYWORDS = {"chronology", "jcckit"}  # PSystemBuilder.java:162,184 commented out
EXTRA_KEYWORDS = {"crash"}  # core/DiagramType.java:113, not a LanguageDescriptor pair
PENDING_MODELS = {"CrashDiagramFactory"}  # UBrex commands arrive with T07
KNOWN_DIAGRAM_DIVERGENCE = {
    "pairs/sprites.puml": "ListSpriteDiagram is built as DiagramType.HELP "
    "(klimt/sprite/ListSpriteDiagram.java:60); the model carries the factory type SPRITES",
}
UML_FACTORY_PREFIX = [
    "PSystemWelcomeFactory",
    "PSystemColorsFactory",
    "SequenceDiagramFactory",
    "ClassDiagramFactory",
    "ActivityDiagramFactory",
    "DescriptionDiagramFactory",
    "StateDiagramFactory",
    "ActivityDiagramFactory3",
]


@pytest.fixture(scope="module")
def models() -> ResolvedModels:
    return resolve(load_dir(MODEL_DIR))


@pytest.fixture(scope="module")
def document(models: ResolvedModels) -> ResolvedModel:
    return models[DOCUMENT_ID]


def rel(path: Path) -> str:
    return path.relative_to(FIXTURES).as_posix()


def expected(path: Path) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = json.loads(path.with_suffix(".json").read_text())["blocks"]
    return blocks


def start_map_for(path: Path) -> dict[str, list[str]] | None:
    return {"uml": SINGLE_LINE_FACTORIES} if path.parent.name == SINGLE_LINE_GROUP else None


@pytest.mark.parametrize("path", PUML, ids=rel)
def test_interpreter_verdict_equals_expected(models: ResolvedModels, path: Path) -> None:
    start_map = start_map_for(path)
    got = [
        accepts(models, block, raw=True, start_map=start_map)
        for block in split_blocks(path.read_text())
    ]
    want = expected(path)
    assert [g["accepted"] for g in got] == [w["accepted"] for w in want]
    if rel(path) in KNOWN_DIAGRAM_DIVERGENCE:
        return
    for verdict, block in zip(got, want, strict=True):
        if block["diagram"] is not None:
            assert verdict["diagram"] == block["diagram"]


@pytest.mark.corpus
def test_expected_verdicts_equal_the_oracle() -> None:
    from tools.validate.oracle import oracle_verdicts

    verdicts = oracle_verdicts(PUML)
    for path in PUML:
        oracle = [
            {"accepted": b["accepted"], "diagram": b["diagram_type"] if b["accepted"] else None}
            for b in verdicts[str(path)]
        ]
        assert oracle == expected(path), rel(path)


@pytest.mark.parametrize("keyword", DIRECTIVE_PAIRS)
def test_every_directive_pair_has_an_accepted_fixture(keyword: str) -> None:
    path = FIXTURES / "pairs" / f"{keyword}.puml"
    lines = path.read_text().splitlines()
    assert lines[0].startswith(f"@start{keyword}")
    assert lines[-1] == f"@end{keyword}"
    assert [b["accepted"] for b in expected(path)] == [True]


def test_start_map_mirrors_find_start_types_and_factory_order(document: ResolvedModel) -> None:
    table = document.start_map
    assert set(table) == (set(DIRECTIVE_PAIRS) | EXTRA_KEYWORDS) - NO_FACTORY_KEYWORDS
    assert table["uml"][: len(UML_FACTORY_PREFIX)] == UML_FACTORY_PREFIX
    assert table["uml"][-2:] == ["TimingDiagramFactory", "HelpFactory"]
    assert table["gantt"] == table["project"] == ["GanttDiagramFactory"]
    assert table["sprites"] == ["ListSpriteDiagramFactory"]
    assert all("PSystemPathFactory" not in names for names in table.values())


def test_every_mapped_factory_has_one_top_model(
    models: ResolvedModels, document: ResolvedModel
) -> None:
    tops = top_models(models)
    mapped = {name for names in document.start_map.values() for name in names}
    assert mapped - set(tops) <= PENDING_MODELS
    # Family models replace generated/embedded ones over time, so assert the invariant
    # (each factory's top model declares that factory; the two activity factories stay
    # distinct) rather than pinning ids.
    assert all(models[mid].factory == factory for factory, mid in tops.items())
    assert tops["ActivityDiagramFactory"] != tops["ActivityDiagramFactory3"]


def opaque_factories() -> list[str]:
    found = []
    for path in sorted(EXTRACTED.glob("*Factory*.json")):
        for item in json.loads(path.read_text()).get("unreachable", []):
            simple = item["class"].rsplit(".", 1)[-1]
            if item["reason"] == OPAQUE_REASON and simple == path.stem:
                found.append(simple)
    return found


def test_every_opaque_extracted_factory_has_an_embedded_model(models: ResolvedModels) -> None:
    factories = opaque_factories()
    assert len(factories) == 24
    tops = top_models(models)

    def embedded_based(mid: str) -> bool:
        # The embedded model is the top, or a family model that includes it is.
        top = models[mid]
        return mid.startswith(EMBEDDED_PREFIX) or any(
            inc.startswith(EMBEDDED_PREFIX) for inc in top.includes
        )

    assert {f: embedded_based(tops[f]) for f in factories} == dict.fromkeys(factories, True)


def rule(model: ResolvedModel, context: str, command: str) -> dict[str, Any]:
    return next(e for e in model.contexts[context] if e["command"] == command)


@pytest.mark.parametrize(
    ("line", "matches"),
    [
        ("@startuml", True),
        ("@startuml foo", True),
        ("@startuml(id=x)", True),
        ("@startumlfoo", True),
        ("\\startuml", True),
        ("@startUML", True),
        ("@STARTUML", False),
        ("@start uml", False),
    ],
)
def test_start_rule_accepts_upstream_name_forms(
    document: ResolvedModel, line: str, matches: bool
) -> None:
    pattern = compile_part(rule(document, "main", "StartUml")["parts"])
    assert (pattern.fullmatch(line) is not None) is matches


def test_any_end_directive_closes_and_text_outside_is_ignored(document: ResolvedModel) -> None:
    end = rule(document, "block", "EndDirective")
    assert end["pop"] is True
    assert compile_part(end["parts"]).fullmatch("@endmindmap") is not None
    assert compile_part(end["parts"]).fullmatch("\\enduml") is not None
    outside = document.contexts["main"][-1]
    assert outside["command"] == "OutsideText"
    assert compile_part(outside["parts"]).fullmatch("any text ]]] at all") is not None


def test_d4_types_enter_opaque_embed_contexts(document: ResolvedModel) -> None:
    targets = {e["command"]: e["push"] for e in document.contexts["main"] if "push" in e}
    for keyword in DIRECTIVE_PAIRS:
        want = f"embed_{keyword}" if keyword in D4_OPAQUE else "block"
        assert targets[f"Start{keyword.capitalize()}"] == want
    for keyword in D4_OPAQUE:
        commands = [e["command"] for e in document.contexts[f"embed_{keyword}"]]
        assert (commands[0], commands[-1]) == ("EndDirective", "OpaqueLine")


def test_nested_start_restarts_the_block(document: ResolvedModel) -> None:
    restart = rule(document, "block", "StartMindmap")
    assert restart["set"] == "block"
    assert rule(document, "block", "StartDot")["set"] == "embed_dot"
    assert rule(document, "block", "StartOther")["set"] == "block"
