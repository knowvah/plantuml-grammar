"""JSON diagrams (T29, ``model/diagrams/json.yaml``).

``json`` refines the T13 base ``embedded-json`` (opaque) for ``JsonDiagramFactory`` and
includes ``style`` for the StyleParser token grammar. ``main`` is StyleExtractor's header
state, ``json_content`` the state after the first data line. The JSON text itself never
decides acceptance (JsonDiagramFactory.java:94-96 catches ParseException); failures are
entries that need the never-given flag ``json_throws`` and fail at the ``@end`` line.

Fixtures (``tests/fixtures/json``), each with a header before ``@start``::

    ' json: RuleA, RuleB          rule ids the fixture exercises
    ' jar: accepted|rejected      gap/ only: the jar verdict the model cannot reproduce
    ' gap: <reason>               gap/ only

``pos/`` is accepted by the jar as JSON, ``neg/`` rejected (``corpus`` test).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from tools.interp import accepts
from tools.interp.compile import compile_part
from tools.interp.source import split_blocks
from tools.model import Model, ResolvedModel, ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve, top_models
from tools.report.coverage import KIND_OPAQUE, rules_of

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO / "model"
FIXTURES = REPO / "tests" / "fixtures" / "json"
POS, NEG, GAP = "pos", "neg", "gap"
JSON_ID = "json"
BASE_ID = "embedded-json"
STYLE_ID = "style"
JSON_STYLE_ID = "json-style"
FACTORY = "JsonDiagramFactory"
FACTORY_CLASS = "net.sourceforge.plantuml.jsondiagram.JsonDiagramFactory"
DIAGRAM = "JSON"
MAIN, CONTENT, EMPTY = "main", "json_content", "empty"
STATE_CONTEXTS = (MAIN, CONTENT)
THROWS = "json_throws"
JOINER = ""
ACCEPTED = "accepted"
UPSTREAM_PREFIX = "src/main/java/net/sourceforge/plantuml/"
HEADER = re.compile(r"^' (?P<key>json|jar|gap): (?P<value>.+)$")
# Entries only the emitters use (the interpreter always matches an earlier entry).
EMITTER_ONLY = {"JsonStyleStructure"}
FAILURES = {
    "JsonStyleError",
    "JsonStyleUnclosed",
    "JsonSkinparamUnclosed",
    "JsonHighlightError",
}
UNTRIMMED = {"JsonHighlight", "JsonHighlightError", "JsonHashLine"}


@pytest.fixture(scope="module")
def raw_models() -> dict[str, Model]:
    return load_dir(MODEL_DIR)


@pytest.fixture(scope="module")
def models(raw_models: dict[str, Model]) -> ResolvedModels:
    return resolve(raw_models)


@pytest.fixture(scope="module")
def json_model(models: ResolvedModels) -> ResolvedModel:
    return models[JSON_ID]


def entries(model: ResolvedModel, context: str) -> list[dict[str, Any]]:
    return list(model.contexts[context])


def commands(model: ResolvedModel, context: str) -> list[str]:
    return [e["command"] for e in entries(model, context)]


def all_entries(model: ResolvedModel) -> list[dict[str, Any]]:
    return [e for ctx in model.contexts.values() for e in ctx]


def variable_regex(model: ResolvedModel, name: str) -> Any:
    return compile_part(model.variables[name])


# --- the model ------------------------------------------------------------------------


def test_json_is_the_top_model_of_its_factory(
    raw_models: dict[str, Model], models: ResolvedModels
) -> None:
    raw = raw_models[JSON_ID]
    assert (raw.layer, raw.diagram, raw.factory) == ("diagram", DIAGRAM, FACTORY)
    assert raw.include == [BASE_ID, JSON_STYLE_ID]
    assert (raw_models[JSON_STYLE_ID].layer, raw_models[JSON_STYLE_ID].include) == (
        "shared",
        [STYLE_ID],
    )
    assert top_models(models)[FACTORY] == JSON_ID


def test_base_contexts_are_shadowed_without_opaque_entries(json_model: ResolvedModel) -> None:
    assert all(e["kind"] != KIND_OPAQUE for e in all_entries(json_model))
    assert commands(json_model, EMPTY) == ["JsonEmptyBody"]


def test_coverage_counts_the_factory_as_modeled(models: ResolvedModels) -> None:
    counts = rules_of(models, JSON_ID)
    assert counts[FACTORY_CLASS] >= 1
    assert counts[f"opaque:{FACTORY_CLASS}"] == 0


def test_header_state_order_mirrors_style_extractor(json_model: ResolvedModel) -> None:
    assert commands(json_model, MAIN) == [
        "JsonStyleError",
        "JsonStyle",
        "JsonStyleUnclosed",
        "JsonStyleStructure",
        "JsonAssume",
        "JsonPragma",
        "JsonHide",
        "JsonScale",
        "JsonTitle",
        "JsonSkin",
        "JsonSkinparamBlock",
        "JsonSkinparamUnclosed",
        "JsonSkinparam",
        "JsonHighlight",
        "JsonHighlightError",
        "JsonHashLine",
        "JsonCommentLine",
        "JsonMemberLine",
        "JsonText",
    ]


def test_data_lines_end_the_header(json_model: ResolvedModel) -> None:
    data = {"JsonHighlight", "JsonHighlightError", "JsonHashLine", "JsonCommentLine"}
    data |= {"JsonMemberLine", "JsonText"}
    setters = {e["command"] for e in entries(json_model, MAIN) if "set" in e}
    assert setters == data
    assert {e["set"] for e in entries(json_model, MAIN) if "set" in e} == {CONTENT}
    assert data <= set(commands(json_model, CONTENT))
    assert not any("set" in e for e in entries(json_model, CONTENT))


def test_only_the_header_style_and_skinparam_need_their_end(
    json_model: ResolvedModel,
) -> None:
    required = {e["command"] for e in all_entries(json_model) if e.get("require_pop")}
    assert required == {"JsonStyle", "JsonSkinparamBlock"}
    (content_style,) = [
        e for e in entries(json_model, CONTENT) if e["command"] == "JsonStyleContent"
    ]
    assert content_style["push"] == "json_style_region"
    assert "require_pop" not in content_style


@pytest.mark.parametrize("context", STATE_CONTEXTS)
def test_failures_need_the_never_given_flag_and_are_not_emitted(
    json_model: ResolvedModel, context: str
) -> None:
    failing = [e for e in entries(json_model, context) if e.get("needs")]
    assert {e["command"] for e in failing} <= FAILURES
    assert all(e["needs"] == THROWS and e["emit"] is False for e in failing)
    assert not any(e.get("gives") == THROWS for e in all_entries(json_model))


def test_untrimmed_entries_are_the_hash_lines(json_model: ResolvedModel) -> None:
    untrimmed = {e["command"] for e in all_entries(json_model) if e.get("trim") is False}
    assert untrimmed == UNTRIMMED


def test_hand_written_entries_cite_upstream_file_and_line(raw_models: dict[str, Model]) -> None:
    for ctx in raw_models[JSON_ID].contexts.values():
        for entry in ctx:
            prov = entry["provenance"]
            assert prov["file"].startswith(UPSTREAM_PREFIX), entry["command"]
            assert isinstance(prov["line"], int), entry["command"]


# --- fragments --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ('#highlight "lastName"', True),
        ('#highlight "address" / "city"', True),
        ("#highlight a <<x>>", True),
        ("#highlight a <<x> y>>", True),
        ("#highlight   a   ", True),
        ("#highlight a<<x>>", True),
        ("#highlight <<x>>", False),
        ("#highlight a<b", False),
        ("#highlight a <<x>> b", False),
        ("#highlight ", False),
        ("#highlight  \t ", False),
        ("#highlight a <<x >>", False),
    ],
)
def test_highlight_line_follows_highlighted_build(
    json_model: ResolvedModel, line: str, expected: bool
) -> None:
    regex = variable_regex(json_model, "JSON_HIGHLIGHT_LINE")
    assert (regex.fullmatch(line) is not None) is expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ('{"a": 1}', True),
        ("title", True),
        ("skinparam", True),
        ("<STYLE>", True),
        ("}", True),
        ("title x", False),
        ("skinparam x", False),
        ("skin rose", False),
        ("scale 2", False),
        ("hide x", False),
        ("!pragma x", False),
        ("!assume x", False),
        ("<style>", False),
    ],
)
def test_first_data_line_excludes_header_lines(
    json_model: ResolvedModel, line: str, expected: bool
) -> None:
    regex = variable_regex(json_model, "JSON_TEXT_FIRST")
    assert (regex.fullmatch(line) is not None) is expected


@pytest.mark.parametrize(
    ("line", "expected"), [("BackgroundColor red", True), ("}", False), ("}x", True)]
)
def test_skinparam_body_line_never_closes(
    json_model: ResolvedModel, line: str, expected: bool
) -> None:
    regex = variable_regex(json_model, "JSON_SKINPARAM_LINE")
    assert (regex.fullmatch(line) is not None) is expected


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (["node { BackgroundColor red }"], False),
        (["Prop red {"], False),
        (["{"], False),
        (["foo // c"], False),
        (["a, b {", "}"], False),
        (["*"], True),
        ([", a"], True),
        (["a,", "b {", "}"], True),
        ([":x y {", "}"], True),
        (["node {", ":depth(1)", "{", "}", "}"], True),
        (["node { BackgroundColor red }", "*"], True),
        (["a, // c"], True),
        (["x* /* c // d"], True),
        (["node", "/* c", ": '/"], True),
    ],
)
def test_style_error_region_marks_non_parsing_exceptions(
    json_model: ResolvedModel, body: list[str], expected: bool
) -> None:
    regex = variable_regex(json_model, "JSON_STYLE_ERROR_REGION")
    text = JOINER.join(["<style>", *body, "</style>"])
    assert (regex.fullmatch(text) is not None) is expected


def test_style_error_region_spans_exactly_one_region(json_model: ResolvedModel) -> None:
    regex = variable_regex(json_model, "JSON_STYLE_ERROR_REGION")
    two = JOINER.join(["<style>", "node {", "}", "</style>", "*", "</style>"])
    assert regex.fullmatch(two) is None
    assert regex.fullmatch(JOINER.join(["<style>", "*"])) is None


# --- fixtures ---------------------------------------------------------------------------


def fixtures(group: str) -> list[Path]:
    return sorted((FIXTURES / group).glob("*.puml"))


def rel(path: Path) -> str:
    return f"{path.parent.name}/{path.stem}"


def header(path: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = HEADER.match(line)
        if match:
            found[match["key"]] = match["value"]
    return found


def fixture_commands(path: Path) -> list[str]:
    return [c.strip() for c in header(path)["json"].split(",")]


def verdict(models: ResolvedModels, path: Path) -> Any:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    return accepts(models, block, raw=True)


def block_line_count(path: Path) -> int:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    return len(block.split("\n"))


@pytest.mark.parametrize("path", fixtures(POS), ids=rel)
def test_pos_fixture_is_accepted(models: ResolvedModels, path: Path) -> None:
    got = verdict(models, path)
    assert got["accepted"], got["first_failure"]
    assert (got["diagram"], got["model"]) == (DIAGRAM, JSON_ID)


@pytest.mark.parametrize("path", fixtures(NEG), ids=rel)
def test_neg_fixture_fails_at_the_end_line(models: ResolvedModels, path: Path) -> None:
    got = verdict(models, path)
    assert got["accepted"] is False
    assert got["first_failure"]["line"] == block_line_count(path)


def gap_params() -> list[Any]:
    return [
        pytest.param(p, id=rel(p), marks=pytest.mark.xfail(strict=True, reason=header(p)["gap"]))
        for p in fixtures(GAP)
    ]


@pytest.mark.parametrize("path", gap_params())
def test_gap_fixture_matches_the_jar(models: ResolvedModels, path: Path) -> None:
    assert verdict(models, path)["accepted"] is (header(path)["jar"] == ACCEPTED)


def test_every_fixture_names_known_commands(json_model: ResolvedModel) -> None:
    known = {c for ctx in json_model.contexts.values() for c in (e["command"] for e in ctx)}
    for path in fixtures(POS) + fixtures(NEG) + fixtures(GAP):
        assert set(fixture_commands(path)) <= known, rel(path)


def test_every_state_command_has_a_fixture(json_model: ResolvedModel) -> None:
    named = {c for p in fixtures(POS) + fixtures(NEG) for c in fixture_commands(p)}
    state = {c for ctx in (*STATE_CONTEXTS, EMPTY) for c in commands(json_model, ctx)}
    assert state - EMITTER_ONLY <= named
    assert {c for p in fixtures(NEG) for c in fixture_commands(p)} >= FAILURES


@pytest.mark.corpus
def test_fixture_verdicts_equal_the_oracle() -> None:
    from tools.validate.oracle import oracle_verdicts

    paths = fixtures(POS) + fixtures(NEG) + fixtures(GAP)
    verdicts = oracle_verdicts(paths)
    for path in paths:
        (block,) = verdicts[str(path)]
        wanted = header(path)["jar"] == ACCEPTED if path.parent.name == GAP else None
        assert block["accepted"] is (path.parent.name == POS if wanted is None else wanted)
        if block["accepted"]:
            assert block["diagram_type"] == DIAGRAM, rel(path)
        else:
            assert block["error_line"] == len(path.read_text(encoding="utf-8").splitlines())
