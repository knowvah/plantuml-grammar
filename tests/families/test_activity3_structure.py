"""Activity diagrams, new syntax: structure (T21b, ``model/diagrams/activity3-structure*.yaml``).

``activity3-structure`` turns CommandPartition3 into a push of ``a3_group_body`` and makes
the generated group closers rejects outside it (closeGroup fails unless a group is the
innermost instruction). ``activity3-structure-lanes`` tracks the swimlane strategy in
the top-level frame: ``a3_main`` (undecided, shadowing T21a's) sets ``a3_lanes_main``
on a swimlane and ``a3_nolanes_main`` on a deciding command, through head copies of the
generated entries.

Fixtures (``tests/fixtures/activity3/structure``) use T21a's header convention::

    ' activity3: CommandA, CommandB        rule ids the fixture exercises
    ' gap: <reason>                        gap/ only: why the model cannot reject it yet
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
from tools.model.resolve import resolve

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "activity3" / "structure"
POS, NEG, GAP = "pos", "neg", "gap"
ACTIVITY3_ID, DIAGRAM = "activity3", "ACTIVITY"
STRUCTURE_ID, LANES_ID = "activity3-structure", "activity3-structure-lanes"
START_MAP = {"uml": ["ActivityDiagramFactory3"]}
HEADER = re.compile(r"^' (?P<key>activity3|gap): (?P<value>.+)$")
UPSTREAM_PREFIX = "src/main/java/net/sourceforge/plantuml/"
DIAGRAM_CLASS = "net.sourceforge.plantuml.activitydiagram3.ActivityDiagram3"

STATEMENTS, REJECT_FLOW = "a3_statements", "a3_reject_flow"
UNDECIDED, ALLOWED, FORBIDDEN = "a3_main", "a3_lanes_main", "a3_nolanes_main"
DECIDE, REJECT_LANES = "a3_lanes_decide", "a3_reject_lanes"
SPLIT_TOP, SPLIT_BODY, GROUP_BODY = "a3_split_top", "a3_split_body", "a3_group_body"

# The class split: T21b's rule ids.
T21B_COMMANDS = (
    "CommandFootboxIgnored CommandSwimlane CommandSwimlane2 CommandPartition3 "
    "CommandCloseGroup3 CommandCloseGroupLegacy3 CommandNote3 CommandNoteLong3"
).split()

# Hand-written entry -> (generated original, guard): "same" parts, or the generated
# sequence with the A3_NOT_ARROW / A3_NOT_DETACH / A3_NOT_PARTITION guards (and the color
# prefix dropped).
SAME, LIST_GUARDS, LONG_UNCOLORED, NOT_PARTITION = "same", "list", "long", "partition"
COPIES = {
    "Activity3LaneFirst": ("CommandSwimlane", SAME),
    "Activity3Lane2First": ("CommandSwimlane2", SAME),
    "Activity3ActivityDecides": ("CommandActivity3", SAME),
    "Activity3SplitUndecided": ("CommandSplit3", SAME),
    "Activity3StartDecides": ("CommandStart3", SAME),
    "Activity3StopDecides": ("CommandStop3", SAME),
    "Activity3SpotDecides": ("CommandCircleSpot3", SAME),
    "Activity3BreakDecides": ("CommandBreak", SAME),
    "Activity3EndDecides": ("CommandEnd3", SAME),
    "Activity3ActivityLongDecides": ("CommandActivityLong3", LONG_UNCOLORED),
    "Activity3ActivityListDecides": ("CommandActivityList", LIST_GUARDS),
    "Activity3LaneAfterActivity": ("CommandSwimlane", SAME),
    "Activity3Lane2AfterActivity": ("CommandSwimlane2", SAME),
    "Activity3SplitEndTop": ("CommandSplitEnd3", SAME),
    "Activity3GroupClose": ("CommandCloseGroup3", SAME),
    "Activity3GroupCloseLegacy": ("CommandCloseGroupLegacy3", NOT_PARTITION),
}
LANE_COPIES = ["Activity3LaneFirst", "Activity3Lane2First"]
DECIDING_COPIES = [
    "Activity3ActivityDecides",
    "Activity3StartDecides",
    "Activity3StopDecides",
    "Activity3SpotDecides",
    "Activity3BreakDecides",
    "Activity3EndDecides",
    "Activity3ActivityLongDecides",
    "Activity3ActivityListDecides",
]
# Upstream order (ActivityDiagramFactory3.java:108-160).
DECIDE_ORDER = [*LANE_COPIES, "Activity3ActivityDecides", "Activity3SplitUndecided"] + [
    c for c in DECIDING_COPIES if c != "Activity3ActivityDecides"
]
TRANSITIONS = {
    **{c: ("set", ALLOWED) for c in LANE_COPIES},
    **{c: ("set", FORBIDDEN) for c in DECIDING_COPIES},
    "Activity3SplitUndecided": ("set", SPLIT_TOP),
    "Activity3SplitEndTop": ("set", ALLOWED),
    "Activity3GroupClose": ("pop", True),
    "Activity3GroupCloseLegacy": ("pop", True),
}
REJECTS = ["Activity3LaneAfterActivity", "Activity3Lane2AfterActivity"]

# copy -> lines it must take (each is a line its generated original takes first).
SAMPLES = {
    "Activity3LaneFirst": ("|A|", "|#red|B| Lane B", "| C |"),
    "Activity3Lane2First": ("swimlane A", 'swimlane #red B as "b"'),
    "Activity3ActivityDecides": (":a;", "<<input>> :b;", ":c; <<task>>"),
    "Activity3SplitUndecided": ("split", "split;"),
    "Activity3StartDecides": ("start", "start;"),
    "Activity3StopDecides": ("stop", "STOP;"),
    "Activity3SpotDecides": ("(A)", "#red:(B);"),
    "Activity3BreakDecides": ("break", "break;"),
    "Activity3EndDecides": ("end", "end <<x>>"),
    "Activity3ActivityLongDecides": (":first line", ":a; more"),
    "Activity3ActivityListDecides": ("- foo", "* bar", "--> x", "-baz"),
    "Activity3SplitEndTop": ("end split", "split end;"),
    "Activity3GroupClose": ("}",),
    "Activity3GroupCloseLegacy": ("end group", "groupend;", "endgroup", "end group;"),
}
# Lines an EARLIER generated command takes: the guarded copies must leave them alone.
GUARDED_OUT = {
    "Activity3ActivityListDecides": ("-> x;", "-[#red]-> x;", "->", "- foo detach", "* x detach;"),
    "Activity3ActivityLongDecides": (":foo detach", ":a; detach;", "#red:foo"),
    "Activity3GroupCloseLegacy": ("group end", "group end;", "GROUP END"),
}


@pytest.fixture(scope="module")
def raw_models() -> dict[str, Model]:
    return load_dir(REPO / "model")


@pytest.fixture(scope="module")
def act(raw_models: dict[str, Model]) -> ResolvedModel:
    return resolve(raw_models)[ACTIVITY3_ID]


@pytest.fixture(scope="module")
def models(raw_models: dict[str, Model]) -> ResolvedModels:
    return resolve(raw_models)


def commands(entries: list[dict[str, Any]]) -> list[str]:
    return [e.get("command", "") for e in entries]


def entry(act: ResolvedModel, context: str, command: str) -> dict[str, Any]:
    (found,) = [e for e in act.contexts[context] if e.get("command") == command]
    return found


def generated(act: ResolvedModel, command: str) -> dict[str, Any]:
    return entry(act, STATEMENTS, command)


def fullmatch(part: Any, text: str) -> bool:
    return compile_part(part).fullmatch(text) is not None


def hand_written(raw_models: dict[str, Model]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for mid in (STRUCTURE_ID, LANES_ID):
        for entries in raw_models[mid].contexts.values():
            found.update({e["command"]: e for e in entries if "command" in e})
    return found


def where(act: ResolvedModel, command: str) -> str:
    return next(c for c, es in act.contexts.items() if command in commands(es))


# --- the model ------------------------------------------------------------------------


def test_structure_is_included_before_the_core_models(raw_models: dict[str, Model]) -> None:
    include = raw_models[ACTIVITY3_ID].include
    assert include.index(STRUCTURE_ID) == include.index("common") + 1
    assert include.index(STRUCTURE_ID) < include.index("activity3-core-flow")
    for mid in (STRUCTURE_ID, LANES_ID):
        assert (raw_models[mid].layer, raw_models[mid].diagram) == ("shared", None)


def test_top_level_contexts_are_heads_then_t21a_top_level(act: ResolvedModel) -> None:
    flow = commands(act.contexts[REJECT_FLOW]) + commands(act.contexts[STATEMENTS])
    assert commands(act.contexts[ALLOWED]) == flow
    assert commands(act.contexts[UNDECIDED]) == DECIDE_ORDER + flow
    assert commands(act.contexts["main"]) == DECIDE_ORDER + flow
    assert commands(act.contexts[FORBIDDEN]) == REJECTS + flow
    split_top = commands(act.contexts[SPLIT_TOP])
    assert split_top == ["Activity3SplitEndTop", *commands(act.contexts[SPLIT_BODY])]


def test_group_body_is_closers_then_every_flow_closer_rejected(act: ResolvedModel) -> None:
    got = commands(act.contexts[GROUP_BODY])
    closers = ["Activity3GroupClose", "Activity3GroupCloseLegacy"]
    rest = commands(act.contexts[REJECT_FLOW]) + commands(act.contexts[STATEMENTS])
    assert got == closers + rest


@pytest.mark.parametrize("context", [UNDECIDED, ALLOWED, FORBIDDEN, GROUP_BODY, "a3_if_then"])
def test_group_commands_are_refined_in_every_context(act: ResolvedModel, context: str) -> None:
    partition = entry(act, context, "CommandPartition3")
    assert (partition["push"], partition["refined_by"]) == (GROUP_BODY, STRUCTURE_ID)
    assert "require_pop" not in partition
    for closer in ("CommandCloseGroup3", "CommandCloseGroupLegacy3"):
        found = entry(act, context, closer)
        assert (found["reject"], found["refined_by"]) == (True, STRUCTURE_ID)


@pytest.mark.parametrize("copy", sorted(COPIES))
def test_copy_equals_its_generated_entry(act: ResolvedModel, copy: str) -> None:
    original, how = COPIES[copy]
    gen = generated(act, original)
    mine = entry(act, where(act, copy), copy)
    assert (mine["kind"], mine.get("end")) == (gen["kind"], gen.get("end"))
    want = gen["parts"]
    if how == LIST_GUARDS:
        want = {
            "seq": [act.variables["A3_NOT_ARROW"], *want["seq"], act.variables["A3_NOT_DETACH"]]
        }
    elif how == LONG_UNCOLORED:
        want = {"seq": [*want["seq"][1:], act.variables["A3_NOT_DETACH"]]}
    elif how == NOT_PARTITION:
        want = {"seq": [act.variables["A3_NOT_PARTITION"], *want["seq"]]}
    assert mine["parts"] == want


@pytest.mark.parametrize(("copy", "transition"), sorted(TRANSITIONS.items()))
def test_copy_carries_its_transition(act: ResolvedModel, copy: str, transition: Any) -> None:
    key, value = transition
    mine = entry(act, where(act, copy), copy)
    assert mine[key] == value
    assert not {"push", "pop", "set"} - {key} & set(mine)
    # State heads are interpreter-only; the group closers (pop) must reach the emitters.
    assert mine.get("emit") is (False if key == "set" else None)


def test_lane_rejects_are_rejects(act: ResolvedModel) -> None:
    for copy in REJECTS:
        found = entry(act, REJECT_LANES, copy)
        assert (found["kind"], found["reject"]) == ("single", True)


def test_hand_written_entries_cite_activity_diagram3(raw_models: dict[str, Model]) -> None:
    found = hand_written(raw_models)
    assert set(found) == set(COPIES)
    for name, e in found.items():
        prov = e["provenance"]
        assert prov["class"] == DIAGRAM_CLASS, name
        assert prov["file"].startswith(UPSTREAM_PREFIX), name
        assert len(prov["also"]) == 2, name
        assert all(a.startswith(UPSTREAM_PREFIX) for a in prov["also"]), name


def test_patch_keys_are_t21b_commands(raw_models: dict[str, Model]) -> None:
    raw = raw_models[STRUCTURE_ID]
    assert set(raw.overrides) == {
        "CommandPartition3",
        "CommandCloseGroup3",
        "CommandCloseGroupLegacy3",
    }
    assert not raw.insert_before and not raw.insert_after
    assert not raw_models[LANES_ID].overrides


# --- head copies keep upstream's first match ------------------------------------------


@pytest.mark.parametrize("copy", sorted(SAMPLES))
def test_copy_takes_its_samples(act: ResolvedModel, copy: str) -> None:
    mine = entry(act, where(act, copy), copy)
    original = generated(act, COPIES[copy][0])
    for text in SAMPLES[copy]:
        assert fullmatch(mine["parts"], text), text
        assert fullmatch(original["parts"], text), text


@pytest.mark.parametrize("copy", sorted(SAMPLES))
def test_no_earlier_generated_command_takes_the_samples(act: ResolvedModel, copy: str) -> None:
    order = commands(act.contexts[STATEMENTS])
    earlier = act.contexts[STATEMENTS][: order.index(COPIES[copy][0])]
    for e in earlier:
        for text in SAMPLES[copy]:
            assert not fullmatch(e["parts"], text), (e["command"], text)


def test_decide_copies_precede_no_closer_reject(act: ResolvedModel) -> None:
    # The copies sit before T21a's top-level rejects; no line may reach both.
    rejects = act.contexts[REJECT_FLOW]
    for copy in DECIDE_ORDER:
        for text in SAMPLES[copy]:
            assert not any(fullmatch(e["parts"], text) for e in rejects), (copy, text)


@pytest.mark.parametrize("copy", sorted(GUARDED_OUT))
def test_guards_leave_earlier_commands_lines_alone(act: ResolvedModel, copy: str) -> None:
    mine = entry(act, where(act, copy), copy)
    for text in GUARDED_OUT[copy]:
        assert not fullmatch(mine["parts"], text), text


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


def test_every_fixture_names_known_commands(act: ResolvedModel) -> None:
    known = set(commands(act.contexts[STATEMENTS]))
    for path in fixtures(POS) + fixtures(NEG) + fixtures(GAP):
        assert set(fixture_commands(path)) <= known, rel(path)


@pytest.mark.parametrize("group", [POS, NEG])
def test_every_t21b_command_has_a_fixture(group: str) -> None:
    covered = {c for path in fixtures(group) for c in fixture_commands(path)}
    assert set(T21B_COMMANDS) <= covered


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
