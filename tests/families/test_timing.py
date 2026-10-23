"""Timing diagrams (T23, ``model/diagrams/timing.yaml`` + ``timing-errors.yaml``).

``timing`` extends ``gen-timing-diagram`` and ``common``. ``main`` is the state before any
current player exists (two head rejects, then the generated list); CommandRobustConcise
and CommandAtPlayer ``set`` the ``timing_player`` context. ``timing-errors`` narrows the
commands whose execute step fails on the line's shape and follows each with a reject.

Fixtures (``tests/fixtures/timing``), each with a header before ``@start``::

    ' timing: CommandA, CommandB          rule ids the fixture exercises
    ' gap: <reason>                       gap/ only: why the model cannot reject it

``pos/`` is accepted by the jar as TIMING, ``neg/`` and ``gap/`` are rejected by the jar
(``corpus`` test). The interpreter runs each fixture raw with dispatch restricted to
TimingDiagramFactory: the jar rejects only when every factory rejects, and a positive
fixture names TIMING, so the restricted verdict must match.
"""

from __future__ import annotations

import random
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
FIXTURES = REPO / "tests" / "fixtures" / "timing"
POS, NEG, GAP = "pos", "neg", "gap"
TIMING_ID = "timing"
ERRORS_ID = "timing-errors"
GENERATED_ID = "gen-timing-diagram"
COMMON_ID = "common"
FACTORY = "TimingDiagramFactory"
DIAGRAM = "TIMING"
MAIN, PLAYER = "main", "timing_player"
BODY_CONTEXTS = (MAIN, PLAYER)
START_MAP = {"uml": [FACTORY]}
UPSTREAM_PREFIX = "src/main/java/net/sourceforge/plantuml/"
# TimingDiagramFactory.java:85-86: the common block, then CommandFootboxIgnored.
FIRST_TIMING_COMMAND = "CommandFootboxIgnored"
HEADER = re.compile(r"^' (?P<key>timing|gap): (?P<value>.+)$")
HEAD_REJECTS = ["TimingStateWithoutPlayer", "TimingConstraintWithoutPlayer"]
PLAYER_SETTERS = ("CommandRobustConcise", "CommandAtPlayer")
JAVA_INT_MAX = 2**31 - 1
JAVA_LONG_MAX = 2**63 - 1


@pytest.fixture(scope="module")
def raw_models() -> dict[str, Model]:
    return load_dir(MODEL_DIR)


@pytest.fixture(scope="module")
def models(raw_models: dict[str, Model]) -> ResolvedModels:
    return resolve(raw_models)


@pytest.fixture(scope="module")
def timing(models: ResolvedModels) -> ResolvedModel:
    return models[TIMING_ID]


def commands(entries: list[dict[str, Any]]) -> list[str]:
    return [e["command"] for e in entries]


def generated_commands(models: ResolvedModels) -> list[str]:
    return commands(models[GENERATED_ID].contexts[MAIN])


def timing_commands(models: ResolvedModels) -> list[str]:
    """Generated rule ids after the common block."""
    generated = generated_commands(models)
    return generated[generated.index(FIRST_TIMING_COMMAND) :]


def entry(model: ResolvedModel, context: str, command: str) -> dict[str, Any]:
    (found,) = [e for e in model.contexts[context] if e["command"] == command]
    return found


# --- the model ------------------------------------------------------------------------


def test_timing_is_the_top_model_of_its_factory(
    raw_models: dict[str, Model], models: ResolvedModels
) -> None:
    raw = raw_models[TIMING_ID]
    assert (raw.layer, raw.diagram, raw.factory) == ("diagram", DIAGRAM, FACTORY)
    assert raw.include == [GENERATED_ID, COMMON_ID, ERRORS_ID]
    assert top_models(models)[FACTORY] == TIMING_ID
    assert (raw_models[ERRORS_ID].layer, raw_models[ERRORS_ID].diagram) == ("shared", None)


def test_main_starts_with_the_no_player_rejects(timing: ResolvedModel) -> None:
    got = timing.contexts[MAIN]
    assert commands(got[: len(HEAD_REJECTS)]) == HEAD_REJECTS
    assert all(e["reject"] is True for e in got[: len(HEAD_REJECTS)])
    assert commands(got[len(HEAD_REJECTS) :]) == commands(timing.contexts[PLAYER])


def test_player_context_keeps_the_generated_order(
    timing: ResolvedModel, models: ResolvedModels
) -> None:
    got = commands(timing.contexts[PLAYER])
    wanted = generated_commands(models)
    assert [c for c in got if c in set(wanted)] == wanted
    assert not set(HEAD_REJECTS) & set(got)


@pytest.mark.parametrize("context", BODY_CONTEXTS)
def test_players_set_the_player_context(timing: ResolvedModel, context: str) -> None:
    for command in PLAYER_SETTERS:
        assert entry(timing, context, command)["set"] == PLAYER, (context, command)
    setters = {e["command"] for e in timing.contexts[context] if "set" in e}
    assert setters == set(PLAYER_SETTERS)


@pytest.mark.parametrize("context", BODY_CONTEXTS)
def test_each_reject_sits_next_to_its_narrowed_rule(
    raw_models: dict[str, Model], timing: ResolvedModel, context: str
) -> None:
    errors = raw_models[ERRORS_ID]
    assert set(errors.insert_after) <= set(errors.overrides)
    assert set(errors.insert_before) <= set(errors.overrides)
    got = commands(timing.contexts[context])
    for key, (inserted,) in errors.insert_after.items():
        assert inserted["reject"] is True
        assert got[got.index(key) + 1] == inserted["command"], (context, key)
    for key, (inserted,) in errors.insert_before.items():
        assert inserted["reject"] is True
        assert got[got.index(key) - 1] == inserted["command"], (context, key)


def test_every_patch_key_matches_a_timing_rule(
    raw_models: dict[str, Model], models: ResolvedModels
) -> None:
    wanted = set(timing_commands(models))
    for mid in (TIMING_ID, ERRORS_ID):
        raw = raw_models[mid]
        keys = set(raw.overrides) | set(raw.insert_before) | set(raw.insert_after)
        assert keys and keys <= wanted, mid


def hand_written(raw_models: dict[str, Model]) -> list[dict[str, Any]]:
    errors = raw_models[ERRORS_ID]
    out = [e for g in (errors.insert_before, errors.insert_after) for es in g.values() for e in es]
    out += [e for es in raw_models[TIMING_ID].contexts.values() for e in es if "command" in e]
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
    keys = {k for mid in (TIMING_ID, ERRORS_ID) for k in raw_models[mid].overrides}
    for item in raw_models[TIMING_ID].contexts[MAIN]:
        if "command" in item:
            simple = item["provenance"]["class"].rsplit(".", 1)[-1]
            assert simple not in keys, item["command"]


# --- fragments ------------------------------------------------------------------------


def matches(models: ResolvedModels, name: str, text: str) -> bool:
    return compile_part(models[ERRORS_ID].variables[name]).fullmatch(text) is not None


@pytest.mark.parametrize(
    ("name", "text", "expected"),
    [
        ("T_TIME_OK", ":start", True),
        ("T_TIME_OK", ":start+5", True),
        ("T_TIME_OK", ":start-.5", True),
        ("T_TIME_OK", ":start+5.", True),
        ("T_TIME_OK", ":start+.", False),
        ("T_TIME_OK", ":start+1.2.3", False),
        ("T_TIME_OK", "2019/07/02", True),
        ("T_TIME_OK", "2147483648/1/1", False),
        ("T_TIME_OK", "0002147483647:0:0", True),
        ("T_TIME_OK", "1:2:2147483648", False),
        ("T_TIME_OK", "+12.5", True),
        ("T_TIME_OK", "-3", True),
        ("T_TIME_OK", "clk*2147483647", True),
        ("T_TIME_OK", "clk*2147483648", False),
        ("T_TIME_HOUR_BAD", "5:0:99999999999", True),
        ("T_TIME_HOUR_BAD", "2147483648:0:0", True),
        ("T_TIME_HOUR_BAD", "1:2147483648:0", True),
        ("T_TIME_HOUR_BAD", "2147483647:2147483647:2147483647", False),
        ("T_LONG_POSITIVE", "0", False),
        ("T_LONG_POSITIVE", "000", False),
        ("T_LONG_POSITIVE", "007", True),
        ("T_LONG_POSITIVE", "9223372036854775807", True),
        ("T_LONG_POSITIVE", "9223372036854775808", False),
    ],
)
def test_time_and_number_fragments(
    models: ResolvedModels, name: str, text: str, expected: bool
) -> None:
    assert matches(models, name, text) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('"yyyy-MM-dd HH:mm:ss.SSS"', True),
        ('"G y M d k H m s S E D F w W a K h z Z Y u X L"', True),
        ("\"YY-MM-dd 'at' HH:mm\"", True),
        ("\"''\"", True),
        ("\"'it''s'\"", True),
        ('"XXX"', True),
        ('"é"', True),
        ('"XXXX"', False),
        ('"b"', False),
        ('"q"', False),
        ('"\'"', False),
        ("\"'abc'X'\"", False),
        ("\"a''b\"", False),
    ],
)
def test_date_format_fragment(models: ResolvedModels, text: str, expected: bool) -> None:
    assert matches(models, "T_DATE_FORMAT_OK", text) is expected


def random_numbers(seed: int) -> list[int]:
    rng = random.Random(seed)
    edges = [JAVA_INT_MAX, JAVA_INT_MAX + 1, JAVA_LONG_MAX, JAVA_LONG_MAX + 1, 1, 10**10]
    return edges + [rng.randint(1, 10 ** rng.randint(1, 21)) for _ in range(3000)]


def test_long_range_agrees_with_java_long_bounds(models: ResolvedModels) -> None:
    for n in random_numbers(23):
        assert matches(models, "T_LONG_POSITIVE", str(n)) is (n <= JAVA_LONG_MAX), n


def test_hour_overflow_agrees_with_java_int_bounds(models: ResolvedModels) -> None:
    for n in random_numbers(31):
        assert matches(models, "T_TIME_HOUR_BAD", f"1:2:{n}") is (n > JAVA_INT_MAX), n
        assert matches(models, "T_TIME_OK", f"1:{n}:2") is (n <= JAVA_INT_MAX), n


# --- fixtures -------------------------------------------------------------------------


def fixtures(group: str) -> list[Path]:
    return sorted((FIXTURES / group).glob("*.puml"))


def header(path: Path) -> dict[str, str]:
    found = (HEADER.match(line) for line in path.read_text(encoding="utf-8").splitlines())
    return {m["key"]: m["value"] for m in found if m}


def fixture_commands(path: Path) -> list[str]:
    return [c.strip() for c in header(path)["timing"].split(",")]


def rel(path: Path) -> str:
    return path.relative_to(FIXTURES).as_posix()


def restricted(models: ResolvedModels, path: Path) -> Any:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    return accepts(models, block, raw=True, start_map=START_MAP)


@pytest.mark.parametrize("path", fixtures(POS), ids=rel)
def test_pos_fixture_is_accepted(models: ResolvedModels, path: Path) -> None:
    verdict = restricted(models, path)
    assert verdict["accepted"], verdict["first_failure"]
    assert (verdict["diagram"], verdict["model"]) == (DIAGRAM, TIMING_ID)


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
def test_pos_fixture_is_timing_with_full_dispatch(models: ResolvedModels, path: Path) -> None:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    verdict = accepts(models, block, raw=True)
    assert (verdict["accepted"], verdict["diagram"]) == (True, DIAGRAM)


def test_every_fixture_names_known_commands(models: ResolvedModels) -> None:
    known = set(timing_commands(models))
    for path in fixtures(POS) + fixtures(NEG) + fixtures(GAP):
        assert set(fixture_commands(path)) <= known, rel(path)


@pytest.mark.parametrize("group", [POS, NEG])
def test_every_timing_command_has_a_fixture(models: ResolvedModels, group: str) -> None:
    covered = {c for path in fixtures(group) for c in fixture_commands(path)}
    assert set(timing_commands(models)) <= covered


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
