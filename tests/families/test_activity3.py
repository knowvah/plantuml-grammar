"""Activity diagrams, new syntax (T21a core: ``model/diagrams/activity3*.yaml``).

``activity3`` extends ``gen-activity-diagram3`` and ``common``. ``activity3-core-flow``
gives the generated flow openers and closers a transition and defines one body context
per construct; ``activity3-core-reject`` holds one ``reject`` context per closer family,
spliced at the head of every body the closer does not belong to (ActivityDiagram3 fails
a closer whose construct is not the innermost open instruction);
``activity3-core-actions`` fixes CommandKill3's regex precedence.

Fixtures (``tests/fixtures/activity3``), each with a header before ``@start``::

    ' activity3: CommandA, CommandB        rule ids the fixture exercises
    ' gap: <reason>                        gap/ only: why the model cannot reject it yet

``pos/`` is accepted by the jar as ACTIVITY, ``neg/`` and ``gap/`` are rejected by the
jar (``corpus`` test). The interpreter runs each fixture raw with dispatch restricted to
ActivityDiagramFactory3.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from tests.helpers.models import repo_models, repo_resolved
from tools.interp import accepts
from tools.interp.compile import compile_part
from tools.interp.source import split_blocks
from tools.model import Model, ResolvedModel, ResolvedModels
from tools.model.resolve import top_models

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO / "model"
FIXTURES = REPO / "tests" / "fixtures" / "activity3"
POS, NEG, GAP = "pos", "neg", "gap"
ACTIVITY3_ID = "activity3"
FLOW_ID, REJECT_ID, ACTIONS_ID = (
    "activity3-core-flow",
    "activity3-core-reject",
    "activity3-core-actions",
)
CORE_IDS = (FLOW_ID, REJECT_ID, ACTIONS_ID)
# T21b (tests/families/test_activity3_structure.py): included between common and the core
# models; its swimlane-strategy heads lead the top level.
STRUCTURE_ID, T21B_TOP_HEADS = "activity3-structure", "a3_lanes_decide"
GENERATED_ID = "gen-activity-diagram3"
FACTORY = "ActivityDiagramFactory3"
DIAGRAM = "ACTIVITY"
START_MAP = {"uml": [FACTORY]}
UPSTREAM_PREFIX = "src/main/java/net/sourceforge/plantuml/"
STATEMENTS = "a3_statements"
HEADER = re.compile(r"^' (?P<key>activity3|gap): (?P<value>.+)$")
# ActivityDiagramFactory3.java:105-107: CommandFootboxIgnored, then the common block.
FIRST_ACTIVITY_COMMAND = "CommandSwimlane"

# The class split: T21a's rule ids.
T21A_COMMANDS = (
    "CommandArrow3 CommandArrowLong3 CommandRepeat3 CommandActivity3 CommandIf4 CommandIf2 "
    "CommandDecoratorMultine_55 CommandIfLegacy1 CommandElseIf3 CommandElseIf2 CommandElse3 "
    "CommandDecoratorMultine_60 CommandElseLegacy1 CommandEndif3 CommandSwitch CommandCase "
    "CommandEndSwitch CommandRepeatWhile3 CommandRepeatWhile3Multilines CommandBackward3 "
    "CommandBackwardLong3 CommandWhile3 CommandWhileEnd3 CommandFork3 CommandForkAgain3 "
    "CommandForkEnd3 CommandSplit3 CommandSplitAgain3 CommandSplitEnd3 CommandStart3 "
    "CommandStop3 CommandCircleSpot3 CommandBreak CommandEnd3 CommandKill3 CommandLink3 "
    "CommandActivityLong3 CommandActivityList CommandLabel CommandGoto CommandDecoratorMultine_91"
).split()
# Every line starting with `-` that no arrow takes falls back to CommandActivityList
# (ActivityDiagramFactory3.java:160), and arrow execution fails only on unknown colors
# (gap/arrow-unknown-color).
NO_NEG_FIXTURE = {
    "CommandArrow3": "a `-` line no arrow regex takes is an activity (CommandActivityList)",
    "CommandArrowLong3": "a `-` line no arrow regex takes is an activity (CommandActivityList)",
}

IF_THEN, IF_ELSE = "a3_if_then", "a3_if_else"
SWITCH_HEAD, SWITCH_CASE = "a3_switch_head", "a3_switch_case"
REPEAT, WHILE, FORK, SPLIT = "a3_repeat_body", "a3_while_body", "a3_fork_body", "a3_split_body"
BODIES = ("main", IF_THEN, IF_ELSE, SWITCH_HEAD, SWITCH_CASE, REPEAT, WHILE, FORK, SPLIT)

TRANSITIONS = {
    "CommandIf4": ("push", IF_THEN),
    "CommandIf2": ("push", IF_THEN),
    "CommandDecoratorMultine_55": ("push", IF_THEN),
    "CommandIfLegacy1": ("push", IF_THEN),
    "CommandElse3": ("set", IF_ELSE),
    "CommandDecoratorMultine_60": ("set", IF_ELSE),
    "CommandElseLegacy1": ("set", IF_ELSE),
    "CommandEndif3": ("pop", True),
    "CommandSwitch": ("push", SWITCH_HEAD),
    "CommandCase": ("set", SWITCH_CASE),
    "CommandEndSwitch": ("pop", True),
    "CommandRepeat3": ("push", REPEAT),
    "CommandRepeatWhile3": ("pop", True),
    "CommandRepeatWhile3Multilines": ("pop", True),
    "CommandWhile3": ("push", WHILE),
    "CommandWhileEnd3": ("pop", True),
    "CommandFork3": ("push", FORK),
    "CommandForkEnd3": ("pop", True),
    "CommandSplit3": ("push", SPLIT),
    "CommandSplitEnd3": ("pop", True),
}
NO_TRANSITION = (
    "CommandElseIf3",
    "CommandElseIf2",
    "CommandDecoratorMultine_91",
    "CommandForkAgain3",
    "CommandSplitAgain3",
    "CommandBackward3",
    "CommandBackwardLong3",
)

ELSE, ENDIF = "Activity3ElseWithoutIf", "Activity3EndifWithoutIf"
CASE, ENDSWITCH = "Activity3CaseWithoutSwitch", "Activity3EndSwitchWithoutSwitch"
REPEAT_WHILE, BACKWARD = "Activity3RepeatWhileWithoutRepeat", "Activity3BackwardWithoutLoop"
ENDWHILE = "Activity3EndWhileWithoutWhile"
FORK_CLOSER, SPLIT_CLOSER = "Activity3ForkCloserWithoutFork", "Activity3SplitCloserWithoutSplit"
BEFORE_CASE = [
    "Activity3ActivityBeforeCase",
    "Activity3ActivityListBeforeCase",
    "Activity3KillBeforeCase",
]
ALL_CLOSERS = [
    ELSE,
    ENDIF,
    CASE,
    ENDSWITCH,
    REPEAT_WHILE,
    BACKWARD,
    ENDWHILE,
    FORK_CLOSER,
    SPLIT_CLOSER,
]
HEADS = {
    "main": ALL_CLOSERS,
    IF_THEN: [CASE, ENDSWITCH, REPEAT_WHILE, BACKWARD, ENDWHILE, FORK_CLOSER, SPLIT_CLOSER],
    IF_ELSE: [ELSE, CASE, ENDSWITCH, REPEAT_WHILE, BACKWARD, ENDWHILE, FORK_CLOSER, SPLIT_CLOSER],
    SWITCH_HEAD: [
        *BEFORE_CASE,
        ELSE,
        ENDIF,
        REPEAT_WHILE,
        BACKWARD,
        ENDWHILE,
        FORK_CLOSER,
        SPLIT_CLOSER,
    ],
    SWITCH_CASE: [ELSE, ENDIF, REPEAT_WHILE, BACKWARD, ENDWHILE, FORK_CLOSER, SPLIT_CLOSER],
    REPEAT: [ELSE, ENDIF, CASE, ENDSWITCH, ENDWHILE, FORK_CLOSER, SPLIT_CLOSER],
    WHILE: [ELSE, ENDIF, CASE, ENDSWITCH, REPEAT_WHILE, FORK_CLOSER, SPLIT_CLOSER],
    FORK: [ELSE, ENDIF, CASE, ENDSWITCH, REPEAT_WHILE, BACKWARD, ENDWHILE, SPLIT_CLOSER],
    SPLIT: [ELSE, ENDIF, CASE, ENDSWITCH, REPEAT_WHILE, BACKWARD, ENDWHILE, FORK_CLOSER],
}

# shape variable -> (generated commands of the family, lines the shape must match)
SHAPES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "A3_ELSE_SHAPE": (
        (
            "CommandElseIf3",
            "CommandElseIf2",
            "CommandElse3",
            "CommandDecoratorMultine_60",
            "CommandElseLegacy1",
            "CommandDecoratorMultine_91",
        ),
        (
            "else",
            "ELSE (no)",
            "elseif (b) then",
            "else if (b) then (x)",
            "(foo) elseif (b) then",
            "else when y",
            "elseif (c) is (d) then",
            "else (-> bar)",
            "else (multi",
            "(foo) elseif (b",
        ),
    ),
    "A3_ENDIF_SHAPE": (("CommandEndif3",), ("endif", "end if", "endif;", "EndIf <<x>>")),
    "A3_CASE_SHAPE": (("CommandCase",), ("case (a)", "case(a)", "CASE (b) ")),
    "A3_ENDSWITCH_SHAPE": (("CommandEndSwitch",), ("endswitch", "endswitch <<x>>")),
    "A3_REPEAT_WHILE_SHAPE": (
        ("CommandRepeatWhile3", "CommandRepeatWhile3Multilines"),
        ("repeat while (a)", "repeatwhile (a) is (y) not (n)", "repeat while (a", "repeat while"),
    ),
    "A3_BACKWARD_SHAPE": (
        ("CommandBackward3", "CommandBackwardLong3"),
        ("backward :x;", "(in) backward :x; (out)", "backward :x", "backward: x;"),
    ),
    "A3_ENDWHILE_SHAPE": (
        ("CommandWhileEnd3",),
        ("endwhile", "end while", "while end", "endwhile (no)"),
    ),
    "A3_FORK_CLOSER_SHAPE": (
        ("CommandForkAgain3", "CommandForkEnd3"),
        (
            "fork again",
            "end fork",
            "fork end",
            "forkend",
            "end merge",
            "end fork {or}",
            "fork again;",
        ),
    ),
    "A3_SPLIT_CLOSER_SHAPE": (
        ("CommandSplitAgain3", "CommandSplitEnd3"),
        ("split again", "end split", "split end", "splitend;"),
    ),
    "A3_ACTIVITY_SHAPE": (("CommandActivity3", "CommandActivityLong3"), (":x;", ":x", "<<s>> :x;")),
    "A3_ACTIVITY_LIST_SHAPE": (("CommandActivityList",), ("- foo", "* bar", "-baz", "--> x")),
    "A3_KILL_SHAPE": (("CommandKill3",), ("kill", "detach;", "killer", "KILL now")),
}
# Openers and plain statements no shape may take.
NOT_A_CLOSER = (
    "fork",
    "fork;",
    "fork <<x>>",
    "split",
    "split;",
    "repeat",
    "repeat :x;",
    "while (a)",
    "while (end)",
    "if (a) then",
    "if (else) then",
    "switch (x)",
    "start",
    "stop",
    "end",
    ":else;",
    "endless",
    "casework",
    "forked",
    "elsewhere",
    "title else",
    "-> x;",
    "-[#red]-> x;",
    "->",
    "(A)",
    "note right: backward",
    "#red:while (a)",
    "#red:repeat",
    "#red:else foo",
    "#red:elseif (b) then",
)


@pytest.fixture(scope="module")
def raw_models() -> dict[str, Model]:
    return repo_models()


@pytest.fixture(scope="module")
def models(raw_models: dict[str, Model]) -> ResolvedModels:
    return repo_resolved()


@pytest.fixture(scope="module")
def act(models: ResolvedModels) -> ResolvedModel:
    return models[ACTIVITY3_ID]


def commands(entries: list[dict[str, Any]]) -> list[str]:
    return [e["command"] for e in entries]


def generated_commands(models: ResolvedModels) -> list[str]:
    return commands(models[GENERATED_ID].contexts["main"])


def activity_commands(models: ResolvedModels) -> list[str]:
    """Generated rule ids after the common block."""
    generated = generated_commands(models)
    return generated[generated.index(FIRST_ACTIVITY_COMMAND) :]


def entries_named(model: ResolvedModel, context: str, command: str) -> list[dict[str, Any]]:
    return [e for e in model.contexts[context] if e["command"] == command]


def statement_entries(act: ResolvedModel) -> list[dict[str, Any]]:
    return act.contexts[STATEMENTS]


def fullmatch(part: Any, text: str) -> bool:
    return compile_part(part).fullmatch(text) is not None


# --- the model ------------------------------------------------------------------------


def test_activity3_is_the_top_model_of_its_factory(
    raw_models: dict[str, Model], models: ResolvedModels
) -> None:
    raw = raw_models[ACTIVITY3_ID]
    assert (raw.layer, raw.diagram, raw.factory) == ("diagram", DIAGRAM, FACTORY)
    assert raw.include == [GENERATED_ID, "common", STRUCTURE_ID, *CORE_IDS]
    assert top_models(models)[FACTORY] == ACTIVITY3_ID
    for mid in CORE_IDS:
        assert (raw_models[mid].layer, raw_models[mid].diagram) == ("shared", None)


def test_the_class_split_covers_every_activity_command(models: ResolvedModels) -> None:
    t21b = {
        "CommandSwimlane",
        "CommandSwimlane2",
        "CommandPartition3",
        "CommandCloseGroup3",
        "CommandCloseGroupLegacy3",
        "CommandNote3",
        "CommandNoteLong3",
    }
    got = activity_commands(models)
    assert sorted(got) == sorted([*T21A_COMMANDS, *t21b])
    assert len(T21A_COMMANDS) == 41


@pytest.mark.parametrize("context", BODIES)
def test_each_body_is_its_head_rejects_then_the_generated_order(
    act: ResolvedModel, models: ResolvedModels, context: str
) -> None:
    entries = act.contexts[context]
    if context == "main":  # T21b's swimlane-strategy heads come first (structure-lanes)
        entries = entries[len(act.contexts[T21B_TOP_HEADS]) :]
    got = commands(entries)
    head = HEADS[context]
    assert got[: len(head)] == head
    assert all(e.get("reject") is True for e in entries[: len(head)])
    wanted = generated_commands(models)
    assert [c for c in got[len(head) :] if c in set(wanted)] == wanted
    assert not set(got[len(head) :]) & set(ALL_CLOSERS + BEFORE_CASE)


@pytest.mark.parametrize(("command", "transition"), sorted(TRANSITIONS.items()))
def test_flow_commands_carry_their_transition(
    act: ResolvedModel, command: str, transition: tuple[str, Any]
) -> None:
    key, value = transition
    for context in BODIES:
        (found,) = entries_named(act, context, command)
        assert found[key] == value, context
        assert found["refined_by"] == FLOW_ID
        assert "require_pop" not in found, context


def test_stay_commands_have_no_transition(act: ResolvedModel) -> None:
    for command in NO_TRANSITION:
        (found,) = entries_named(act, "main", command)
        assert not {"push", "pop", "set"} & set(found), command


def test_no_flow_entry_requires_a_pop(act: ResolvedModel) -> None:
    # Unclosed constructs are accepted: no checkFinalError override (AbstractDiagram.java:162).
    mine = set(T21A_COMMANDS) | set(ALL_CLOSERS) | set(BEFORE_CASE)
    flow = [e for es in act.contexts.values() for e in es if e["command"] in mine]
    assert len(flow) > len(mine)
    assert not any(e.get("require_pop") for e in flow)


def test_every_patch_key_matches_a_generated_rule(
    raw_models: dict[str, Model], models: ResolvedModels
) -> None:
    wanted = set(activity_commands(models))
    for mid in CORE_IDS:
        raw = raw_models[mid]
        keys = set(raw.overrides) | set(raw.insert_before) | set(raw.insert_after)
        assert keys <= wanted, mid
    assert set(raw_models[FLOW_ID].overrides) == set(TRANSITIONS)
    assert set(raw_models[ACTIONS_ID].overrides) == {"CommandKill3"}


def hand_written(raw_models: dict[str, Model]) -> list[dict[str, Any]]:
    return [
        e
        for mid in CORE_IDS
        for es in raw_models[mid].contexts.values()
        for e in es
        if "command" in e
    ]


def test_hand_written_entries_are_rejects_citing_upstream(raw_models: dict[str, Model]) -> None:
    entries = hand_written(raw_models)
    assert sorted(commands(entries)) == sorted([*ALL_CLOSERS, *BEFORE_CASE])
    patched = {k for mid in CORE_IDS for k in raw_models[mid].overrides}
    for e in entries:
        prov = e["provenance"]
        assert (e["kind"], e["reject"]) == ("single", True), e["command"]
        assert prov["file"].startswith(UPSTREAM_PREFIX), e["command"]
        assert prov["line"] >= 1, e["command"]
        assert all(a.startswith(UPSTREAM_PREFIX) for a in prov.get("also", [])), e["command"]
        assert prov["class"].rsplit(".", 1)[-1] not in patched, e["command"]


# --- fragments ------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_shape_matches_its_family_samples(act: ResolvedModel, name: str) -> None:
    family, samples = SHAPES[name]
    part = act.variables[name]
    for text in samples:
        assert fullmatch(part, text), text


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_shape_samples_reach_no_other_generated_command(act: ResolvedModel, name: str) -> None:
    family, samples = SHAPES[name]
    for e in statement_entries(act):
        if e["command"] in family:
            continue
        for text in samples:
            assert not fullmatch(e["parts"], text), (e["command"], text)


@pytest.mark.parametrize("text", NOT_A_CLOSER)
def test_no_shape_takes_openers_or_statements(act: ResolvedModel, text: str) -> None:
    closers = [
        n
        for n in SHAPES
        if n not in ("A3_ACTIVITY_SHAPE", "A3_ACTIVITY_LIST_SHAPE", "A3_KILL_SHAPE")
    ]
    for name in closers:
        assert not fullmatch(act.variables[name], text), (name, text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("kill", True),
        ("detach;", True),
        ("killer", True),
        ("KILL now", True),
        ("foo detach", True),
        ("bar detach;", True),
        ("skill", False),
        ("detach x", False),
        ("detached", False),
    ],
)
def test_kill_follows_the_unparenthesized_alternation(
    act: ResolvedModel, text: str, expected: bool
) -> None:
    (kill,) = entries_named(act, STATEMENTS, "CommandKill3")
    assert fullmatch(kill["parts"], text) is expected


# --- fixtures -------------------------------------------------------------------------


def fixtures(group: str) -> list[Path]:
    return sorted((FIXTURES / group).glob("*.puml"))


def header(path: Path) -> dict[str, str]:
    found = (HEADER.match(line) for line in path.read_text(encoding="utf-8").splitlines())
    return {m["key"]: m["value"] for m in found if m}


def fixture_commands(path: Path) -> list[str]:
    return [c.strip() for c in header(path)["activity3"].split(",")]


def rel(path: Path) -> str:
    return path.relative_to(FIXTURES).as_posix()


def restricted(models: ResolvedModels, path: Path) -> Any:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    return accepts(models, block, raw=True, start_map=START_MAP)


@pytest.mark.parametrize("path", fixtures(POS), ids=rel)
def test_pos_fixture_is_accepted(models: ResolvedModels, path: Path) -> None:
    verdict = restricted(models, path)
    assert verdict["accepted"], verdict["first_failure"]
    assert (verdict["diagram"], verdict["model"]) == (DIAGRAM, ACTIVITY3_ID)


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
def test_pos_fixture_is_activity_with_full_dispatch(models: ResolvedModels, path: Path) -> None:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    verdict = accepts(models, block, raw=True)
    assert (verdict["accepted"], verdict["diagram"]) == (True, DIAGRAM)


def test_every_fixture_names_known_commands(models: ResolvedModels) -> None:
    known = set(activity_commands(models))
    for path in fixtures(POS) + fixtures(NEG) + fixtures(GAP):
        assert set(fixture_commands(path)) <= known, rel(path)


@pytest.mark.parametrize("group", [POS, NEG])
def test_every_t21a_command_has_a_fixture(group: str) -> None:
    covered = {c for path in fixtures(group) for c in fixture_commands(path)}
    exempt = set(NO_NEG_FIXTURE) if group == NEG else set()
    assert set(T21A_COMMANDS) - exempt <= covered


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
