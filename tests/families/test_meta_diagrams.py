"""Meta diagrams (T32): ebnf, regex, def, creole and sprite-list models.

One main diagram model per factory, ``model/diagrams/meta-diagrams-<type>.yaml``. The
body grammars of ebnf and regex are checked against ports of upstream in
``test_meta_diagrams_ebnf.py`` and ``test_meta_diagrams_regex.py``.

Fixtures (``tests/fixtures/meta-diagrams``), each with a header before ``@start``::

    ' meta: RuleA, RuleB      rule ids the fixture exercises
    ' gap: <reason>           gap/ only: why the model cannot reproduce the jar

``pos/`` is accepted by the jar, ``neg/`` and ``gap/`` are rejected by the jar (corpus
test). The interpreter runs each fixture raw with full dispatch; ``gap/`` fixtures are
strict xfails (the interpreter accepts them).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from tools.interp import accepts
from tools.interp.source import split_blocks
from tools.model import Model, ResolvedModel, ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve, top_models

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "meta-diagrams"
POS, NEG, GAP = "pos", "neg", "gap"
UPSTREAM_PREFIX = "src/main/java/net/sourceforge/plantuml/"
HEADER = re.compile(r"^' (?P<key>meta|gap): (?P<value>.+)$")
MAIN, EMPTY = "main", "empty"
# type -> (model id, diagram, factory, includes, oracle diagram type of an accepted block)
MODELS = {
    "ebnf": (
        "meta-diagrams-ebnf",
        "EBNF",
        "PSystemEbnfFactory",
        ["gen-psystem-ebnf", "common"],
        "EBNF",
    ),
    "regex": (
        "meta-diagrams-regex",
        "REGEX",
        "PSystemRegexFactory",
        ["gen-psystem-regex", "common"],
        "REGEX",
    ),
    "def": (
        "meta-diagrams-def",
        "DEFINITION",
        "PSystemDefinitionFactory",
        ["embedded-definition"],
        None,
    ),
    "creole": (
        "meta-diagrams-creole",
        "CREOLE",
        "PSystemCreoleFactory",
        ["embedded-creole", "creole"],
        None,
    ),
    "sprites": (
        "meta-diagrams-sprites",
        "SPRITES",
        "ListSpriteDiagramFactory",
        ["gen-list-sprite-diagram", "common"],
        "HELP",
    ),
}
REGEX_ID, EBNF_ID, CREOLE_ID = "meta-diagrams-regex", "meta-diagrams-ebnf", "meta-diagrams-creole"
REGEX_STACKED = "regex_stacked"
REGEX_MAIN_TAIL = ["RegexLineWellFormed", "RegexLineEmpty", "RegexLineUnparsable", "RegexLine"]
REGEX_STACKED_TAIL = ["RegexLineBalanced", "RegexLineStackedUnparsable"]
HAND_WRITTEN = {
    REGEX_ID: [*REGEX_MAIN_TAIL, *REGEX_STACKED_TAIL],
    EBNF_ID: ["EbnfRuleUnparsable", "EbnfRuleMultilines", "EbnfRuleMultilinesUnparsable"],
    CREOLE_ID: ["CreoleNoiseLine", "CreoleBlankLine", "CreoleLine", "CreoleText", "CreoleEnd"],
}
EMITTER_ONLY = {"RegexLine"}  # the interpreter never reaches it (reject before it)


@pytest.fixture(scope="module")
def raw_models() -> dict[str, Model]:
    return load_dir(REPO / "model")


@pytest.fixture(scope="module")
def models(raw_models: dict[str, Model]) -> ResolvedModels:
    return resolve(raw_models)


def commands(entries: list[dict[str, Any]]) -> list[str]:
    return [e["command"] for e in entries]


def entry(model: ResolvedModel, context: str, command: str) -> dict[str, Any]:
    (found,) = [e for e in model.contexts[context] if e["command"] == command]
    return found


# --- the models ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", sorted(MODELS))
def test_main_model_is_the_top_model_of_its_factory(
    raw_models: dict[str, Model], models: ResolvedModels, kind: str
) -> None:
    model_id, diagram, factory, includes, _ = MODELS[kind]
    raw = raw_models[model_id]
    assert raw.path.name == f"meta-diagrams-{kind}.yaml"
    assert (raw.layer, raw.diagram, raw.factory, raw.include) == (
        "diagram",
        diagram,
        factory,
        includes,
    )
    assert top_models(models)[factory] == model_id


@pytest.mark.parametrize(
    ("context", "tail"), [(MAIN, REGEX_MAIN_TAIL), (REGEX_STACKED, REGEX_STACKED_TAIL)]
)
def test_regex_states_splice_the_common_list_then_their_tail(
    models: ResolvedModels, context: str, tail: list[str]
) -> None:
    model = models[REGEX_ID]
    generated = [
        c
        for c in commands(models["gen-psystem-regex"].contexts[MAIN])
        if c != "CommandRegexfSingleLine"
    ]
    got = commands(model.contexts[context])
    assert got[-len(tail) :] == tail
    assert [c for c in got if c in set(generated)] == generated
    assert "CommandRegexfSingleLine" not in got


def test_regex_state_entries(models: ResolvedModels) -> None:
    model = models[REGEX_ID]
    well = entry(model, MAIN, "RegexLineWellFormed")
    assert (well["set"], well["emit"]) == (REGEX_STACKED, False)
    assert entry(model, MAIN, "RegexLineEmpty")["emit"] is False
    assert entry(model, REGEX_STACKED, "RegexLineBalanced")["emit"] is False
    for context, command in [
        (MAIN, "RegexLineUnparsable"),
        (REGEX_STACKED, "RegexLineStackedUnparsable"),
    ]:
        assert entry(model, context, command)["reject"] is True
    defines = {
        model.variables[v]["regex"].split(")(?&rxc)")[0]
        for v in ("RX_WELL_FORMED", "RX_EMPTY", "RX_BALANCED")
    }
    assert len(defines) == 1, "the three state leaves share one DEFINE block"


def test_ebnf_rule_entries_precede_the_generated_rules(models: ResolvedModels) -> None:
    got = commands(models[EBNF_ID].contexts[MAIN])
    i = got.index("CommandEBnfSingleLine")
    assert got[i - 1 : i + 4] == [
        "EbnfRuleUnparsable",
        "CommandEBnfSingleLine",
        "EbnfRuleMultilines",
        "EbnfRuleMultilinesUnparsable",
        "UBrexCommandEbnfMultilines",
    ]
    multi = entry(models[EBNF_ID], MAIN, "EbnfRuleMultilines")
    assert (multi["kind"], multi["join"], multi["emit"]) == (
        "multiline",
        {"max_lines": 100000},
        False,
    )
    generated = entry(models[EBNF_ID], MAIN, "UBrexCommandEbnfMultilines")
    assert (generated["push"], generated["refined_by"]) == ("ebnf_rule_body", EBNF_ID)


def test_creole_flags(models: ResolvedModels) -> None:
    model = models[CREOLE_ID]
    assert commands(model.contexts[MAIN]) == [
        "CreoleNoiseLine",
        "CreoleBlankLine",
        "CreoleLine",
        "CreoleText",
    ]
    assert commands(model.contexts[EMPTY]) == ["CreoleBlankLine", "CreoleEnd"]
    assert entry(model, MAIN, "CreoleNoiseLine")["needs"] == "creole_content"
    assert entry(model, EMPTY, "CreoleEnd")["needs"] == "creole_content"
    for context, command in [
        (MAIN, "CreoleBlankLine"),
        (MAIN, "CreoleLine"),
        (MAIN, "CreoleText"),
        (EMPTY, "CreoleBlankLine"),
    ]:
        assert entry(model, context, command)["gives"] == "creole_content"


def hand_written(raw: Model) -> list[dict[str, Any]]:
    found = [e for ctx in raw.contexts.values() for e in ctx if "command" in e]
    found += [e for es in (*raw.insert_before.values(), *raw.insert_after.values()) for e in es]
    return found


@pytest.mark.parametrize("kind", sorted(MODELS))
def test_hand_written_entries_cite_upstream(raw_models: dict[str, Model], kind: str) -> None:
    raw = raw_models[MODELS[kind][0]]
    patched = set(raw.overrides) | set(raw.insert_before) | set(raw.insert_after)
    for found in hand_written(raw):
        prov = found["provenance"]
        assert prov["file"].startswith(UPSTREAM_PREFIX), prov
        assert isinstance(prov["line"], int), prov
        assert all(c.startswith(UPSTREAM_PREFIX) for c in prov.get("also", [])), prov
        assert prov["class"].rsplit(".", 1)[-1] not in patched, found["command"]


# --- fixtures -----------------------------------------------------------------------------


def fixtures(group: str) -> list[Path]:
    return sorted((FIXTURES / group).glob("*.puml"))


def header(path: Path) -> dict[str, str]:
    found = (HEADER.match(line) for line in path.read_text(encoding="utf-8").splitlines())
    return {m["key"]: m["value"] for m in found if m}


def fixture_commands(path: Path) -> list[str]:
    return [c.strip() for c in header(path)["meta"].split(",")]


def kind_of(path: Path) -> str:
    return path.stem.split("-", 1)[0]


def rel(path: Path) -> str:
    return path.relative_to(FIXTURES).as_posix()


def verdict(models: ResolvedModels, path: Path) -> Any:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    return accepts(models, block, raw=True)


@pytest.mark.parametrize("path", fixtures(POS), ids=rel)
def test_pos_fixture_is_accepted(models: ResolvedModels, path: Path) -> None:
    got = verdict(models, path)
    assert got["accepted"], got["first_failure"]
    model_id, diagram = MODELS[kind_of(path)][:2]
    assert (got["diagram"], got["model"]) == (diagram, model_id)


@pytest.mark.parametrize("path", fixtures(NEG), ids=rel)
def test_neg_fixture_is_rejected(models: ResolvedModels, path: Path) -> None:
    assert verdict(models, path)["accepted"] is False


def gap_params() -> list[Any]:
    return [
        pytest.param(p, id=rel(p), marks=pytest.mark.xfail(strict=True, reason=header(p)["gap"]))
        for p in fixtures(GAP)
    ]


@pytest.mark.parametrize("path", gap_params())
def test_gap_fixture_is_rejected(models: ResolvedModels, path: Path) -> None:
    assert verdict(models, path)["accepted"] is False


def test_every_fixture_names_known_commands(models: ResolvedModels) -> None:
    for path in fixtures(POS) + fixtures(NEG) + fixtures(GAP):
        model = models[MODELS[kind_of(path)][0]]
        known = {e["command"] for ctx in model.contexts.values() for e in ctx}
        assert set(fixture_commands(path)) <= known, rel(path)


def test_every_hand_written_rule_has_a_fixture() -> None:
    covered = {c for path in fixtures(POS) + fixtures(NEG) for c in fixture_commands(path)}
    wanted = {c for rules in HAND_WRITTEN.values() for c in rules} - EMITTER_ONLY
    assert covered >= wanted


@pytest.mark.corpus
def test_fixture_verdicts_equal_the_oracle() -> None:
    from tools.validate.oracle import oracle_verdicts

    paths = fixtures(POS) + fixtures(NEG) + fixtures(GAP)
    verdicts = oracle_verdicts(paths)
    for path in paths:
        (block,) = verdicts[str(path)]
        assert block["accepted"] is (path.parent.name == POS), rel(path)
        if block["accepted"]:
            assert block["diagram_type"] == MODELS[kind_of(path)][4], rel(path)
