"""MindMap and WBS diagrams (T26, ``model/diagrams/mindmap-wbs-*.yaml``).

``mindmap-wbs-mindmap`` and ``mindmap-wbs-wbs`` are the top models of
MindMapDiagramFactory and WBSDiagramFactory. Each includes its generated model and
``common`` and adds line-local execution errors (see the model headers):

* unknown ``[#color]`` node colors (both) and link colors (WBS) as interpreter-only
  ``reject`` entries placed before the command that would capture the color;
* WBS items without a label that are not pseudo nodes (``_``): the two label-optional
  item commands are narrowed and followed by a ``reject`` with the remaining shape.

Tree structure (second WBS root, depth jumps, mindmap indentation multiples) depends on
the previous item's level and on leading blanks the interpreter never sees; those are
gap fixtures.

Fixtures (``tests/fixtures/mindmap-wbs``), one block each, with a header before
``@start``::

    ' mindmap-wbs: RuleA, RuleB   rule ids the fixture exercises
    ' gap: <reason>               gap/ only: why the model cannot reproduce the jar

``pos/`` is accepted and ``neg/`` and ``gap/`` are rejected by the jar (``corpus`` tests).
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from tools.interp import accepts
from tools.interp.compile import compile_part
from tools.interp.source import split_blocks
from tools.model import Model, ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve, top_models

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO / "model"
FIXTURES = REPO / "tests" / "fixtures" / "mindmap-wbs"
POS, NEG, GAP = "pos", "neg", "gap"
COLORS_ID = "mindmap-wbs-colors"
GEN_MINDMAP, GEN_WBS = "gen-mind-map-diagram", "gen-wbs-diagram"
MAIN = "main"
COMMAND, PROVENANCE = "command", "provenance"
UPSTREAM_PREFIX = "src/main/java/"
HEADER = re.compile(r"^' (?P<key>mindmap-wbs|gap): (?P<value>.+)$")
DIAGRAM_OF = {"mindmap": "MINDMAP", "wbs": "WBS"}
BRACKET_UNKNOWN, LINK_UNKNOWN = "MW_BRACKET_COLOR_UNKNOWN", "MW_LINK_COLOR_UNKNOWN"
NARROWED = ("CommandWBSItemNew_44", "CommandWBSItemOld_47")
MODEL_OF = {"mindmap": "mindmap-wbs-mindmap", "wbs": "mindmap-wbs-wbs"}
MINDMAP_ID, WBS_ID = MODEL_OF["mindmap"], MODEL_OF["wbs"]
WORD_BOUNDARY = r"\b"
DIRECTION_LEAF = rf"{WORD_BOUNDARY}(left|right|top|bottom){WORD_BOUNDARY}"

TOPS = {
    MINDMAP_ID: ("MINDMAP", "MindMapDiagramFactory", GEN_MINDMAP),
    WBS_ID: ("WBS", "WBSDiagramFactory", GEN_WBS),
}

# (model, hand-written entry, generated neighbour, "before" | "after").
PLACEMENT = [
    (MINDMAP_ID, "MindMapOrgmodeUnknownColor", "CommandMindMapOrgmodeMultiline", "before"),
    (MINDMAP_ID, "MindMapPlusUnknownColor", "CommandMindMapPlus", "before"),
    (WBS_ID, "WBSItemUnknownColor", "CommandWBSItemNew_43", "before"),
    (WBS_ID, "WBSItemMissingLabel", "CommandWBSItemNew_44", "after"),
    (WBS_ID, "WBSItemOldMissingLabel", "CommandWBSItemOld_47", "after"),
    (WBS_ID, "WBSLinkUnknownColor", "CommandWBSLink", "before"),
]
HAND_WRITTEN = {(model, name) for model, name, _, _ in PLACEMENT}


@cache
def raw_models() -> dict[str, Model]:
    return load_dir(MODEL_DIR)


@cache
def models() -> ResolvedModels:
    return resolve(raw_models())


def entries(model: str) -> list[dict[str, Any]]:
    return list(models()[model].contexts[MAIN])


def command_ids(model: str) -> list[str]:
    return [str(e[COMMAND]) for e in entries(model)]


def entry(model: str, command: str) -> dict[str, Any]:
    return next(e for e in entries(model) if e[COMMAND] == command)


def fixtures(group: str) -> list[Path]:
    return sorted((FIXTURES / group).glob("*.puml"))


def rel(path: Path) -> str:
    return f"{path.parent.name}/{path.stem}"


def header(path: Path) -> dict[str, str]:
    found = (HEADER.match(line) for line in path.read_text(encoding="utf-8").splitlines())
    return {m["key"]: m["value"] for m in found if m}


def kind_of(path: Path) -> str:
    """``mindmap`` or ``wbs``: fixture names start with the start keyword."""
    return path.stem.split("-")[0]


def named_rules(path: Path) -> set[str]:
    return {c.strip() for c in header(path)["mindmap-wbs"].split(",")}


def verdict(path: Path) -> Any:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    return accepts(models(), block, raw=True)


def body_verdict(kind: str, body: str) -> bool:
    block = f"@start{kind}\n{body}\n@end{kind}\n"
    return bool(accepts(models(), block)["accepted"])


def matches(variable: str, text: str) -> bool:
    part = models()[COLORS_ID].variables[variable]
    return compile_part({"seq": [part, {"regex": "[^\\n]*"}]}).fullmatch(text) is not None


# --- model shape -----------------------------------------------------------------------


@pytest.mark.parametrize("model", sorted(TOPS))
def test_family_model_is_the_top_model_of_its_factory(model: str) -> None:
    diagram, factory, generated = TOPS[model]
    found = models()[model]
    assert top_models(models())[factory] == model
    assert (found.layer, found.diagram, found.factory) == ("diagram", diagram, factory)
    assert set(found.includes) >= {generated, "common", COLORS_ID}


@pytest.mark.parametrize("model", sorted(TOPS))
def test_main_keeps_every_generated_command_in_upstream_order(model: str) -> None:
    generated = [str(e[COMMAND]) for e in models()[TOPS[model][2]].contexts[MAIN]]
    assert [c for c in command_ids(model) if c in set(generated)] == generated


@pytest.mark.parametrize("model", sorted(TOPS))
def test_an_empty_body_stays_rejected(model: str) -> None:
    assert "empty" not in models()[model].contexts


@pytest.mark.parametrize(("model", "name", "neighbour", "side"), PLACEMENT)
def test_hand_written_entry_sits_next_to_its_command(
    model: str, name: str, neighbour: str, side: str
) -> None:
    ids = command_ids(model)
    offset = 1 if side == "before" else -1
    assert ids.index(neighbour) - ids.index(name) == offset
    assert entry(model, name)["reject"] is True
    assert entry(model, name)["kind"] == "single"


@pytest.mark.parametrize("command", NARROWED)
def test_label_optional_items_are_narrowed_by_the_wbs_model(command: str) -> None:
    found = entry(WBS_ID, command)
    assert found["refined_by"] == WBS_ID
    assert len(found["parts"]["alt"]) == 2
    assert found[PROVENANCE] == entry(GEN_WBS, command)[PROVENANCE]


def test_direction_word_boundaries_are_folded_into_the_direction_leaf() -> None:
    found = entry(MINDMAP_ID, "CommandMindMapDirection")
    leaves = [str(p["regex"]) for p in found["parts"]["seq"] if "regex" in p]
    assert DIRECTION_LEAF in leaves
    assert WORD_BOUNDARY not in leaves
    assert found["refined_by"] == MINDMAP_ID


def test_hand_written_entries_cite_an_upstream_file_and_line() -> None:
    seen = set()
    for model in TOPS:
        for found in entries(model):
            if "reject" not in found:
                continue
            prov = found[PROVENANCE]
            assert str(prov["file"]).startswith(UPSTREAM_PREFIX), found[COMMAND]
            assert int(prov["line"]) > 0, found[COMMAND]
            if not str(found[COMMAND]).startswith("Command"):
                seen.add((model, str(found[COMMAND])))
    assert seen >= HAND_WRITTEN
    assert {name for _, name in seen} - {name for _, name in HAND_WRITTEN} <= {
        str(e[COMMAND]) for es in raw_models()["common-errors"].insert_after.values() for e in es
    }


# --- color lookaheads (klimt/color/HColorSet.java:78-158) ------------------------------


@pytest.mark.parametrize(
    ("text", "unknown"),
    [
        ("red]", False),
        ("RED]", False),
        ("Business]", False),
        ("automatic]", False),
        ("Transparent]", False),
        ("background]", False),
        ("f]", False),
        ("fff]", False),
        ("ABCDEF]", False),
        ("ffffffff]", False),
        ("ff]", True),
        ("ffff]", True),
        ("fffffff]", True),
        ("zzzz]", True),
        ("red_]", True),
        ("redd]", True),
        ("re]", True),
        ("red-blue]", True),
        ("ä]", True),
        ("]", True),
    ],
)
def test_bracket_color_lookahead(text: str, unknown: bool) -> None:
    assert matches(BRACKET_UNKNOWN, text) is unknown


@pytest.mark.parametrize(
    ("text", "unknown"),
    [
        ("red", False),
        ("red : label", False),
        ("red<<st>>", False),
        ("red-blue", False),
        ("red|0f0", False),
        ("red\\blue", False),
        ("f/abc", False),
        ("Navy:x", False),
        ("zzzz", True),
        ("red-zzz", True),
        ("redd", True),
        ("red-blue-green", True),
        ("red_", True),
        ("ff", True),
    ],
)
def test_link_color_lookahead(text: str, unknown: bool) -> None:
    assert matches(LINK_UNKNOWN, text) is unknown


# --- WBS missing labels (wbs/CommandWBSItemNew.java:121-125) ---------------------------


@pytest.mark.parametrize(
    ("line", "rule"),
    [
        ("**", "WBSItemMissingLabel"),
        ("**<", "WBSItemMissingLabel"),
        ("**>[#red]", "WBSItemMissingLabel"),
        ("**(c)", "WBSItemMissingLabel"),
        ("**(c)[#red]", "WBSItemMissingLabel"),
        ("**_", "CommandWBSItemNew_44"),
        ("**_>", "CommandWBSItemNew_44"),
        ("**_[#red](c)", "CommandWBSItemNew_44"),
        ("** label", "CommandWBSItemNew_44"),
        ("**< label", "CommandWBSItemNew_44"),
        ("**[#red]<", "WBSItemOldMissingLabel"),
        ("**(c)>", "WBSItemOldMissingLabel"),
        ("**[#red]_<", "CommandWBSItemOld_47"),
        ("**(c)[#red]< label", "CommandWBSItemOld_47"),
    ],
)
def test_label_less_items_reach_the_reject_or_the_narrowed_rule(line: str, rule: str) -> None:
    first = next(
        str(e[COMMAND])
        for e in entries(WBS_ID)
        if str(e[COMMAND]).startswith(("WBSItem", "CommandWBSItem"))
        and compile_part(e["parts"]).fullmatch(line)
    )
    assert first == rule


# --- fixtures ----------------------------------------------------------------------------


@pytest.mark.parametrize("path", fixtures(POS), ids=rel)
def test_pos_fixture_is_accepted(path: Path) -> None:
    found = verdict(path)
    assert found["accepted"] is True
    assert found["diagram"] == DIAGRAM_OF[kind_of(path)]


@pytest.mark.parametrize("path", fixtures(NEG), ids=rel)
def test_neg_fixture_is_rejected(path: Path) -> None:
    assert verdict(path)["accepted"] is False


def gap_params() -> list[Any]:
    return [
        pytest.param(p, id=rel(p), marks=pytest.mark.xfail(strict=True, reason=header(p)["gap"]))
        for p in fixtures(GAP)
    ]


@pytest.mark.parametrize("path", gap_params())
def test_gap_fixture_matches_the_jar(path: Path) -> None:
    assert verdict(path)["accepted"] is False


def test_every_fixture_names_rules_of_its_model() -> None:
    for path in fixtures(POS) + fixtures(NEG) + fixtures(GAP):
        assert named_rules(path) <= set(command_ids(MODEL_OF[kind_of(path)])), rel(path)


def test_every_reject_entry_has_a_neg_fixture() -> None:
    covered = set().union(*(named_rules(p) for p in fixtures(NEG)))
    assert {name for _, name in HAND_WRITTEN} <= covered


# --- inline cases (interpreter here, jar in the corpus test) -------------------------

# (start keyword, body, accepted by the jar).
INLINE_CASES = [
    ("mindmap", "* a\n**[#zzzz] b", False),
    ("mindmap", "* a\n** [#zzzz] b", True),
    ("mindmap", "* a\n**_[#zzzz] b", True),
    ("mindmap", "* a\n*+[#zzzz] b", True),
    ("mindmap", "* a\n+-[#zzzz] b", False),
    ("mindmap", "* a\n**[#zzzz]:b", False),
    ("mindmap", "* a\n**[#ä] b", True),
    ("mindmap", "* a\n*** b\n***** c", True),
    ("mindmap", "* a\n* b", True),
    ("mindmap", "title t", True),
    ("mindmap", "* a\nlefty side", False),
    ("mindmap", "* a\nfoo bottom side", True),
    ("wbs", "*_", True),
    ("wbs", "*", False),
    ("wbs", "* a\n**[#red]_<", True),
    ("wbs", "* a\n**[#red]<", False),
    ("wbs", "* a\n**[#ff] b", False),
    ("wbs", "* a\n**<_[#zzzz] b", False),
    ("wbs", "* a\n**[#zzzz]:b", False),
    ("wbs", "* r\n**(a) A\n**(b) B\na -> b #red-blue", True),
    ("wbs", "* r\n**(a) A\n**(b) B\na -> b #redd", False),
    ("wbs", "* r\n**(a) A\n**(b) B\na -> b #f", False),
    ("wbs", "title t", True),
]


@pytest.mark.parametrize(("kind", "body", "accepted"), INLINE_CASES)
def test_inline_case(kind: str, body: str, accepted: bool) -> None:
    assert body_verdict(kind, body) is accepted


# --- corpus: oracle verdicts ----------------------------------------------------------


@pytest.mark.corpus
def test_fixture_verdicts_equal_the_oracle() -> None:
    from tools.validate.oracle import oracle_verdicts

    paths = fixtures(POS) + fixtures(NEG) + fixtures(GAP)
    verdicts = oracle_verdicts(paths)
    for path in paths:
        (block,) = verdicts[str(path)]
        assert block["accepted"] is (path.parent.name == POS), rel(path)
        if path.parent.name == POS:
            assert block["diagram_type"] == DIAGRAM_OF[kind_of(path)], rel(path)


@pytest.mark.corpus
def test_inline_cases_equal_the_oracle(tmp_path: Path) -> None:
    from tools.validate.oracle import oracle_verdicts

    paths = []
    for index, (kind, body, _) in enumerate(INLINE_CASES):
        path = tmp_path / f"case{index}.puml"
        path.write_text(f"@start{kind}\n{body}\n@end{kind}\n", encoding="utf-8")
        paths.append(path)
    verdicts = oracle_verdicts(paths)
    for path, (_, body, accepted) in zip(paths, INLINE_CASES, strict=True):
        assert verdicts[str(path)][0]["accepted"] is accepted, body
