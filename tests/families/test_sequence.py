"""Sequence diagrams (T17, ``model/diagrams/sequence.yaml`` + ``sequence-errors.yaml``).

``sequence`` extends ``gen-sequence-diagram`` and ``common``: groups and boxes become the
``group_body`` / ``box_body`` contexts with their closers at the tail of each context, and
``sequence-errors`` narrows commands whose execute step fails on the line's shape.

Fixtures (``tests/fixtures/sequence``), each with a header before ``@start``::

    ' sequence: CommandA, CommandB        rule ids the fixture exercises
    ' gap: <reason>                       gap/ only: why the model cannot reject it yet

``pos/`` is accepted by the jar as SEQUENCE, ``neg/`` and ``gap/`` are rejected by the jar
(``corpus`` test). The interpreter runs each fixture raw with dispatch restricted to
SequenceDiagramFactory: the jar rejects only when every factory rejects, and a positive
fixture names SEQUENCE, so the restricted verdict must match.
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

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO / "model"
FIXTURES = REPO / "tests" / "fixtures" / "sequence"
POS, NEG, GAP = "pos", "neg", "gap"
SEQUENCE_ID = "sequence"
ERRORS_ID = "sequence-errors"
GENERATED_ID = "gen-sequence-diagram"
COMMON_ID = "common"
FACTORY = "SequenceDiagramFactory"
DIAGRAM = "SEQUENCE"
MAIN, GROUP_BODY, BOX_BODY = "main", "group_body", "box_body"
BODY_CONTEXTS = (MAIN, GROUP_BODY, BOX_BODY)
START_MAP = {"uml": [FACTORY]}
UPSTREAM_PREFIX = "src/main/java/net/sourceforge/plantuml/"
# SequenceDiagramFactory.java:100-101: the common block, then CommandHideUnlinked first.
FIRST_SEQUENCE_COMMAND = "CommandHideUnlinked"
HEADER = re.compile(r"^' (?P<key>sequence|gap): (?P<value>.+)$")
REMOVED = "CommandBoxEnd"
# Every input that matches CommandReturn's regex `return.*` fails only through state or
# an unknown color (CommandReturn.java:108-123): its negative fixtures are gaps.
NO_NEG_FIXTURE = {"CommandReturn": "regex accepts every `return` line; failures are state"}
TAILS = {
    MAIN: ["SequenceBoxEndWithoutBox", "SequenceGroupCloserWithoutGroup"],
    GROUP_BODY: ["SequenceBoxEndInGroup", "SequenceGroupEnd", "SequenceGroupElse"],
    BOX_BODY: ["SequenceBoxEnd", "SequenceGroupCloserInBox"],
}


@pytest.fixture(scope="module")
def raw_models() -> dict[str, Model]:
    return load_dir(MODEL_DIR)


@pytest.fixture(scope="module")
def models(raw_models: dict[str, Model]) -> ResolvedModels:
    return resolve(raw_models)


@pytest.fixture(scope="module")
def seq(models: ResolvedModels) -> ResolvedModel:
    return models[SEQUENCE_ID]


def commands(entries: list[dict[str, Any]]) -> list[str]:
    return [e["command"] for e in entries]


def generated_commands(models: ResolvedModels) -> list[str]:
    return commands(models[GENERATED_ID].contexts[MAIN])


def sequence_commands(models: ResolvedModels) -> list[str]:
    """Generated rule ids after the common block."""
    generated = generated_commands(models)
    return generated[generated.index(FIRST_SEQUENCE_COMMAND) :]


def entry(model: ResolvedModel, context: str, command: str) -> dict[str, Any]:
    (found,) = [e for e in model.contexts[context] if e["command"] == command]
    return found


# --- the model ------------------------------------------------------------------------


def test_sequence_is_the_top_model_of_its_factory(
    raw_models: dict[str, Model], models: ResolvedModels
) -> None:
    raw = raw_models[SEQUENCE_ID]
    assert (raw.layer, raw.diagram, raw.factory) == ("diagram", DIAGRAM, FACTORY)
    assert raw.include == [GENERATED_ID, COMMON_ID, ERRORS_ID]
    assert top_models(models)[FACTORY] == SEQUENCE_ID
    assert (raw_models[ERRORS_ID].layer, raw_models[ERRORS_ID].diagram) == ("shared", None)


@pytest.mark.parametrize("context", BODY_CONTEXTS)
def test_each_body_context_keeps_the_generated_order_then_its_tail(
    seq: ResolvedModel, models: ResolvedModels, context: str
) -> None:
    got = commands(seq.contexts[context])
    assert got[-len(TAILS[context]) :] == TAILS[context]
    wanted = [c for c in generated_commands(models) if c != REMOVED]
    assert [c for c in got if c in set(wanted)] == wanted


def test_group_and_box_starts_push_their_context(seq: ResolvedModel) -> None:
    for context in BODY_CONTEXTS:
        assert entry(seq, context, "CommandGrouping")["push"] == GROUP_BODY
        assert entry(seq, context, "CommandBoxStart")["push"] == BOX_BODY
    assert REMOVED not in commands(seq.contexts[MAIN])


def test_closers_reject_in_main_and_pop_in_their_own_context(seq: ResolvedModel) -> None:
    assert all(entry(seq, MAIN, c).get("reject") for c in TAILS[MAIN])
    assert entry(seq, GROUP_BODY, "SequenceGroupEnd")["pop"] is True
    assert entry(seq, BOX_BODY, "SequenceBoxEnd")["pop"] is True
    lenient = ["SequenceBoxEndInGroup", "SequenceGroupElse", "SequenceGroupCloserInBox"]
    for command in lenient:
        found = [e for c in BODY_CONTEXTS for e in seq.contexts[c] if e["command"] == command]
        assert found and not any(k in found[0] for k in ("pop", "push", "reject")), command


def test_groups_and_boxes_never_require_a_pop(seq: ResolvedModel) -> None:
    # Unclosed groups and boxes are accepted upstream (SequenceDiagram.java:595-600).
    for context in BODY_CONTEXTS:
        for command in ("CommandGrouping", "CommandBoxStart"):
            assert "require_pop" not in entry(seq, context, command), (context, command)


def test_each_reject_directly_follows_its_narrowed_rule(
    raw_models: dict[str, Model], seq: ResolvedModel
) -> None:
    errors = raw_models[ERRORS_ID].insert_after
    assert set(errors) <= set(raw_models[ERRORS_ID].overrides)
    for context in BODY_CONTEXTS:
        got = commands(seq.contexts[context])
        for key, entries in errors.items():
            (inserted,) = entries
            assert inserted["reject"] is True
            assert got[got.index(key) + 1] == inserted["command"], (context, key)


def test_every_patch_key_matches_a_generated_rule(
    raw_models: dict[str, Model], models: ResolvedModels
) -> None:
    wanted = set(sequence_commands(models))
    for mid in (SEQUENCE_ID, ERRORS_ID):
        raw = raw_models[mid]
        keys = set(raw.overrides) | set(raw.insert_before) | set(raw.insert_after)
        assert keys and keys <= wanted, mid


def hand_written(raw_models: dict[str, Model]) -> list[dict[str, Any]]:
    out = [
        e
        for mid in (SEQUENCE_ID, ERRORS_ID)
        for g in raw_models[mid].insert_after.values()
        for e in g
    ]
    for mid in (SEQUENCE_ID, ERRORS_ID):
        out += [e for es in raw_models[mid].contexts.values() for e in es if "command" in e]
    return out


def test_hand_written_entries_cite_upstream_file_and_line(raw_models: dict[str, Model]) -> None:
    entries = hand_written(raw_models)
    assert len(entries) == 13
    for e in entries:
        prov = e["provenance"]
        assert prov["file"].startswith(UPSTREAM_PREFIX), e["command"]
        assert prov["line"] >= 1, e["command"]
        assert all(a.startswith(UPSTREAM_PREFIX) for a in prov.get("also", [])), e["command"]


def test_context_entries_do_not_cite_a_patched_class(raw_models: dict[str, Model]) -> None:
    keys = {k for mid in (SEQUENCE_ID, ERRORS_ID) for k in raw_models[mid].overrides}
    for e in raw_models[SEQUENCE_ID].contexts.values():
        for item in e:
            if "command" in item:
                simple = item["provenance"]["class"].rsplit(".", 1)[-1].replace("$", "_")
                assert simple not in keys, item["command"]


# --- fragments ------------------------------------------------------------------------


def matches(models: ResolvedModels, model_id: str, name: str, text: str) -> bool:
    return compile_part(models[model_id].variables[name]).fullmatch(text) is not None


@pytest.mark.parametrize(
    ("name", "text", "expected"),
    [
        ("GROUP_CLOSER", "end", True),
        ("GROUP_CLOSER", "END", True),
        ("GROUP_CLOSER", "& end", True),
        ("GROUP_CLOSER", "else #pink failure", True),
        ("GROUP_CLOSER", "also", True),
        ("GROUP_CLOSER", "end of loop - retry", True),
        ("GROUP_CLOSER", "else#red", False),
        ("GROUP_CLOSER", "endx", False),
        ("GROUP_END", "else", False),
        ("GROUP_END", "end box", False),
        ("GROUP_END", "end   BOX", False),
        ("GROUP_END", "end boxes", True),
        ("BOX_END", "end box", True),
        ("BOX_END", "endbox", True),
        ("BOX_END", "end box now", False),
        ("ACTIVATE2_NAME", "end", True),
        ("ACTIVATE2_NAME", "end x", False),
        ("ACTIVATE2_NAME", "endpoint", True),
    ],
)
def test_structure_fragment(models: ResolvedModels, name: str, text: str, expected: bool) -> None:
    assert matches(models, SEQUENCE_ID, name, text) is expected


@pytest.mark.parametrize(
    ("name", "text", "expected"),
    [
        ("ARROW_DRESSING_LEFT_VALID", " x", True),
        ("ARROW_DRESSING_LEFT_VALID", " o", False),
        ("ARROW_DRESSING_LEFT_VALID", " o<<", True),
        ("ARROW_DRESSING_RIGHT_VALID", "o ", False),
        ("ARROW_DRESSING_RIGHT_VALID", "X ", True),
        ("ARROW_DRESSING_RIGHT_VALID", ">o ", True),
        ("AUTONUMBER_START", "1.1.1", True),
        ("AUTONUMBER_START", "2147483647", True),
        ("AUTONUMBER_START", "2147483648", False),
        ("AUTONUMBER_START", "1.99999999999", False),
        ("ACROSS", "ACROSS", True),
        ("ACROSS", "accross", False),
    ],
)
def test_error_fragment(models: ResolvedModels, name: str, text: str, expected: bool) -> None:
    assert matches(models, ERRORS_ID, name, text) is expected


# --- fixtures -------------------------------------------------------------------------


def fixtures(group: str) -> list[Path]:
    return sorted((FIXTURES / group).glob("*.puml"))


def header(path: Path) -> dict[str, str]:
    found = (HEADER.match(line) for line in path.read_text(encoding="utf-8").splitlines())
    return {m["key"]: m["value"] for m in found if m}


def fixture_commands(path: Path) -> list[str]:
    return [c.strip() for c in header(path)["sequence"].split(",")]


def rel(path: Path) -> str:
    return path.relative_to(FIXTURES).as_posix()


def restricted(models: ResolvedModels, path: Path) -> Any:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    return accepts(models, block, raw=True, start_map=START_MAP)


@pytest.mark.parametrize("path", fixtures(POS), ids=rel)
def test_pos_fixture_is_accepted(models: ResolvedModels, path: Path) -> None:
    verdict = restricted(models, path)
    assert verdict["accepted"], verdict["first_failure"]
    assert (verdict["diagram"], verdict["model"]) == (DIAGRAM, SEQUENCE_ID)


@pytest.mark.parametrize("path", fixtures(NEG), ids=rel)
def test_neg_fixture_is_rejected(models: ResolvedModels, path: Path) -> None:
    assert restricted(models, path)["accepted"] is False


def gap_params() -> list[Any]:
    return [
        pytest.param(p, id=rel(p), marks=pytest.mark.xfail(strict=True, reason=header(p)["gap"]))
        for p in fixtures(GAP)
    ]


@pytest.mark.parametrize("path", gap_params())
def test_gap_fixture_is_rejected(models: ResolvedModels, path: Path) -> None:
    assert restricted(models, path)["accepted"] is False


@pytest.mark.parametrize("path", fixtures(POS), ids=rel)
def test_pos_fixture_is_sequence_with_full_dispatch(models: ResolvedModels, path: Path) -> None:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    verdict = accepts(models, block, raw=True)
    assert (verdict["accepted"], verdict["diagram"]) == (True, DIAGRAM)


def test_every_fixture_names_known_commands(models: ResolvedModels) -> None:
    known = set(sequence_commands(models))
    for path in fixtures(POS) + fixtures(NEG) + fixtures(GAP):
        assert set(fixture_commands(path)) <= known, rel(path)


@pytest.mark.parametrize("group", [POS, NEG])
def test_every_sequence_command_has_a_fixture(models: ResolvedModels, group: str) -> None:
    covered = {c for path in fixtures(group) for c in fixture_commands(path)}
    exempt = set(NO_NEG_FIXTURE) if group == NEG else set()
    assert set(sequence_commands(models)) - exempt <= covered


@pytest.mark.corpus
def test_fixture_verdicts_equal_the_oracle() -> None:
    from tools.validate.oracle import oracle_verdicts

    paths = fixtures(POS) + fixtures(NEG) + fixtures(GAP)
    verdicts = oracle_verdicts(paths)
    for path in paths:
        (block,) = verdicts[str(path)]
        assert block["accepted"] is (path.parent.name == POS), rel(path)
        if block["accepted"]:
            assert block["diagram_type"] == DIAGRAM, rel(path)
