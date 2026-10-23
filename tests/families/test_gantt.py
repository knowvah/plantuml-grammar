"""Gantt diagrams, non-sentence commands (T24, ``model/diagrams/gantt*.yaml``).

``gantt`` extends ``gen-gantt-diagram``, ``common`` and ``gantt-errors`` (which includes
``gantt-dates``). Its body contexts track two pieces of diagram state with head entries
placed before the spliced generated list:

* ``main``: no task-like entry yet (no separator, group or task); ``gantt_tasks``: some
  exist. Separators and ``[A] -> [B]`` move ``main`` to ``gantt_tasks``; the lookups
  ``A -> B``, ``[A] #color`` and ``note bottom`` fail in ``main``.
* group depth: ``gantt_group_1`` (the first group opened from ``main``, a flat state) and
  ``gantt_group`` (pushed); ``end group`` fails at depth 0.

The 9 NaturalGanttCommand sentences are T25 (``gantt-sentences``, one include line).

Fixtures (``tests/fixtures/gantt``), each with a header before ``@start``::

    ' gantt: CommandA, CommandB          rule ids the fixture exercises
    ' gap: <reason>                      gap/ only: why the model cannot reject it
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
FIXTURES = REPO / "tests" / "fixtures" / "gantt"
POS, NEG, GAP = "pos", "neg", "gap"
GANTT_ID, ERRORS_ID, DATES_ID = "gantt", "gantt-errors", "gantt-dates"
GENERATED_ID, COMMON_ID = "gen-gantt-diagram", "common"
FACTORY, DIAGRAM = "GanttDiagramFactory", "GANTT"
MAIN, TASKS, GROUP_1, GROUP = "main", "gantt_tasks", "gantt_group_1", "gantt_group"
BODY_CONTEXTS = (MAIN, TASKS, GROUP_1, GROUP)
NOTE_FIRST, NOTE_BODY = "gantt_note_first", "gantt_note_body"
START_MAP = {"gantt": [FACTORY]}
UPSTREAM_PREFIX = "src/main/java/net/sourceforge/plantuml/"
# GanttDiagramFactory.java:89-91: the sentences, then the first gantt command.
FIRST_GANTT_COMMAND = "CommandGanttArrow"
REMOVED = ("CommandGroupStart", "CommandGroupEnd")
HEADER = re.compile(r"^' (?P<key>gantt|gap|jar): (?P<value>.+)$")
JAVA_INT_MAX = 2**31 - 1
SENTENCES_ID = "gantt-sentences"
# T25 heads (gantt-sentences inserts them before the T24 heads of each context).
SENTENCE_HEADS = {
    MAIN: [
        "GanttItWithoutTask",
        "GanttFirstTaskSentenceInvalid",
        "GanttFirstTaskSentenceNeedsStart",
        "GanttFirstTaskSentence",
    ],
    TASKS: ["GanttProjectStartsAfterTask"],
    GROUP_1: ["GanttProjectStartsAfterTask"],
    GROUP: ["GanttProjectStartsAfterTask"],
}

# head id -> (generated counterpart, action key, action value, sample line)
HEADS: dict[str, dict[str, tuple[str, str, Any, str]]] = {
    MAIN: {
        "GanttArrowWithoutTask": ("CommandGanttArrow", "reject", True, "A -> B"),
        "GanttFirstTaskByArrow": ("CommandGanttArrow2", "set", TASKS, "[A] -> [B]"),
        "GanttColorWithoutTask": ("CommandColorTask", "reject", True, "[A] #red"),
        "GanttFirstTaskBySeparator": ("CommandSeparator", "set", TASKS, "-- x --"),
        "GanttFirstGroup": ("CommandGroupStart", "set", GROUP_1, "group [G]"),
        "GanttGroupEndWithoutGroup": ("CommandGroupEnd", "reject", True, "end group"),
        "GanttNoteWithoutTask": ("CommandNoteBottom", "reject", True, "note bottom"),
    },
    TASKS: {
        "GanttGroupAtRoot": ("CommandGroupStart", "push", GROUP, "group [G]"),
        "GanttGroupEndAtRoot": ("CommandGroupEnd", "reject", True, "end group"),
    },
    GROUP_1: {
        "GanttGroupInFirstGroup": ("CommandGroupStart", "push", GROUP, "group [G]"),
        "GanttFirstGroupEnd": ("CommandGroupEnd", "set", TASKS, "end group"),
    },
    GROUP: {
        "GanttGroupInGroup": ("CommandGroupStart", "push", GROUP, "group [G]"),
        "GanttGroupEnd": ("CommandGroupEnd", "pop", True, "end group"),
    },
}


@pytest.fixture(scope="module")
def raw_models() -> dict[str, Model]:
    return load_dir(MODEL_DIR)


@pytest.fixture(scope="module")
def models(raw_models: dict[str, Model]) -> ResolvedModels:
    return resolve(raw_models)


@pytest.fixture(scope="module")
def gantt(models: ResolvedModels) -> ResolvedModel:
    return models[GANTT_ID]


def commands(entries: list[dict[str, Any]]) -> list[str]:
    return [e["command"] for e in entries]


def generated(models: ResolvedModels) -> list[dict[str, Any]]:
    return models[GENERATED_ID].contexts[MAIN]


def gantt_commands(models: ResolvedModels) -> list[str]:
    """Generated rule ids of the gantt commands (after the common block)."""
    ids = commands(generated(models))
    return ids[ids.index(FIRST_GANTT_COMMAND) :]


def generated_entry(models: ResolvedModels, command: str) -> dict[str, Any]:
    (found,) = [e for e in generated(models) if e["command"] == command]
    return found


def entry(model: ResolvedModel, context: str, command: str) -> dict[str, Any]:
    (found,) = [e for e in model.contexts[context] if e["command"] == command]
    return found


def spliced(gantt: ResolvedModel, context: str) -> list[dict[str, Any]]:
    return gantt.contexts[context][len(SENTENCE_HEADS[context]) + len(HEADS[context]) :]


# --- the model ------------------------------------------------------------------------


def test_gantt_is_the_top_model_of_its_factory(
    raw_models: dict[str, Model], models: ResolvedModels
) -> None:
    raw = raw_models[GANTT_ID]
    assert (raw.layer, raw.diagram, raw.factory) == ("diagram", DIAGRAM, FACTORY)
    assert raw.include == [GENERATED_ID, COMMON_ID, ERRORS_ID, SENTENCES_ID]
    assert top_models(models)[FACTORY] == GANTT_ID
    for mid in (ERRORS_ID, DATES_ID):
        assert (raw_models[mid].layer, raw_models[mid].diagram) == ("shared", None)


@pytest.mark.parametrize("context", BODY_CONTEXTS)
def test_body_context_is_heads_then_the_generated_order(
    gantt: ResolvedModel, models: ResolvedModels, context: str
) -> None:
    got = commands(gantt.contexts[context])
    first = len(SENTENCE_HEADS[context])
    assert got[:first] == SENTENCE_HEADS[context]
    assert got[first : first + len(HEADS[context])] == list(HEADS[context])
    wanted = [c for c in commands(generated(models)) if c not in REMOVED]
    rest = commands(spliced(gantt, context))
    assert [c for c in rest if c in set(wanted)] == wanted


@pytest.mark.parametrize("context", BODY_CONTEXTS)
def test_heads_carry_their_state_transition(gantt: ResolvedModel, context: str) -> None:
    for head, (_, key, value, _) in HEADS[context].items():
        assert entry(gantt, context, head)[key] == value, (context, head)


@pytest.mark.parametrize("context", BODY_CONTEXTS)
def test_heads_have_the_generated_shape(
    gantt: ResolvedModel, models: ResolvedModels, context: str
) -> None:
    for head, (counterpart, _, _, sample) in HEADS[context].items():
        got = entry(gantt, context, head)["parts"]
        assert got == generated_entry(models, counterpart)["parts"], head
        assert compile_part(got).fullmatch(sample), head


@pytest.mark.parametrize("context", BODY_CONTEXTS)
def test_no_earlier_command_takes_a_head_line(
    gantt: ResolvedModel, models: ResolvedModels, context: str
) -> None:
    """A head runs before the whole list, so no upstream-earlier rule may match it."""
    order = commands(generated(models))
    rest = spliced(gantt, context)
    earlier = rest[: commands(rest).index(FIRST_GANTT_COMMAND)]
    for head, (counterpart, _, _, sample) in HEADS[context].items():
        assert not [e["command"] for e in earlier if compile_part(e["parts"]).fullmatch(sample)]
        between = order[order.index(FIRST_GANTT_COMMAND) : order.index(counterpart)]
        hits = [
            c
            for c in between
            if compile_part(generated_entry(models, c)["parts"]).fullmatch(sample)
        ]
        assert hits == [], (head, hits)


def test_group_commands_are_replaced_by_heads(gantt: ResolvedModel) -> None:
    for context in BODY_CONTEXTS:
        assert not set(REMOVED) & set(commands(gantt.contexts[context]))


@pytest.mark.parametrize("context", (TASKS, GROUP_1, GROUP))
def test_note_enters_its_body(gantt: ResolvedModel, context: str) -> None:
    note = entry(gantt, context, "CommandNoteBottom")
    assert (note["kind"], note["push"], note["require_pop"]) == ("single", NOTE_FIRST, True)
    assert "end" not in note


def test_empty_note_rejects_before_its_emitter_twin(gantt: ResolvedModel) -> None:
    first = gantt.contexts[NOTE_FIRST]
    assert commands(first) == ["GanttNoteEmpty", "GanttNoteEmptyClose", "GanttNoteFirstLine"]
    assert first[0]["reject"] is True and first[1]["pop"] is True
    assert first[0]["parts"] == first[1]["parts"]
    assert first[2]["set"] == NOTE_BODY
    assert commands(gantt.contexts[NOTE_BODY]) == ["GanttNoteEnd", "GanttNoteLine"]


@pytest.mark.parametrize(
    ("text", "is_end"),
    [
        ("end note", True),
        ("END  NOTE", True),
        ("end note", True),
        ("endnote", True),
        ("end", False),
        ("end notes", False),
        ("x end note", False),
        ("", False),
    ],
)
def test_note_lines(gantt: ResolvedModel, text: str, is_end: bool) -> None:
    end = entry(gantt, NOTE_BODY, "GanttNoteEnd")["parts"]
    line = entry(gantt, NOTE_BODY, "GanttNoteLine")["parts"]
    assert (compile_part(end).fullmatch(text) is not None) is is_end
    assert (compile_part(line).fullmatch(text) is not None) is not is_end


# --- execution errors (gantt-errors) ----------------------------------------------------


@pytest.mark.parametrize("context", (TASKS, GROUP_1, GROUP))
def test_each_reject_sits_right_after_its_narrowed_rule(
    raw_models: dict[str, Model], gantt: ResolvedModel, context: str
) -> None:
    errors = raw_models[ERRORS_ID]
    assert set(errors.insert_after) == set(errors.overrides) - {"CommandLanguage"}
    got = commands(gantt.contexts[context])
    for key, (inserted,) in errors.insert_after.items():
        assert inserted["reject"] is True
        assert got[got.index(key) + 1] == inserted["command"], (context, key)


def test_every_patch_key_matches_a_gantt_rule(
    raw_models: dict[str, Model], models: ResolvedModels
) -> None:
    wanted = set(gantt_commands(models))
    for mid in (GANTT_ID, ERRORS_ID):
        raw = raw_models[mid]
        keys = set(raw.overrides) | set(raw.insert_before) | set(raw.insert_after)
        assert keys and keys <= wanted, mid


# reject id -> (generated rule, samples the generated rule matches)
REJECT_SAMPLES = {
    "CommandColorTaskError": ("CommandColorTask", ["[A] #zzz", "[A] #red/#ab", "[A] #red_9"]),
    "CommandWeekNumberStrategyError": (
        "CommandWeekNumberStrategy",
        ["week start on mon 9999999999"],
    ),
    "CommandPrintScaleError": (
        "CommandPrintScale",
        ["printscale daily zoom 1.2.3", "printscale daily with week numbering from 2147483648"],
    ),
    "CommandPrintBetweenError": (
        "CommandPrintBetween",
        [
            "print between 2020-02-30 and D+_",
            "print between 31 apr 2020 and 2147483648 days after start",
            "print between feb 29 1900 and 1 jan 1_",
        ],
    ),
    "CommandFootboxGanttError": ("CommandFootboxGantt", ["footbox", "  footbox"]),
    "CommandTaskCompleteDefaultError": (
        "CommandTaskCompleteDefault",
        ["task default completion to 101", "task completion default to 99999999999 %"],
    ),
}


@pytest.mark.parametrize("reject", sorted(REJECT_SAMPLES))
def test_reject_shape_is_the_generated_shape(
    gantt: ResolvedModel, models: ResolvedModels, reject: str
) -> None:
    rule, samples = REJECT_SAMPLES[reject]
    shape = compile_part(entry(gantt, TASKS, reject)["parts"])
    narrowed = compile_part(entry(gantt, TASKS, rule)["parts"])
    original = compile_part(generated_entry(models, rule)["parts"])
    for sample in samples:
        assert original.fullmatch(sample) and shape.fullmatch(sample), sample
        assert not narrowed.fullmatch(sample), sample


# --- fragments ------------------------------------------------------------------------


def fragment(models: ResolvedModels, name: str) -> Any:
    return compile_part(models[DATES_ID].variables[name])


def is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def month_length(year: int, month: int) -> int:
    lengths = [31, 29 if is_leap(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return lengths[month - 1]


def is_valid(year: int, month: int, day: int) -> bool:
    return 1 <= month <= 12 and 1 <= day <= month_length(year, month)


MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def date_samples(seed: int) -> list[tuple[int, int, int]]:
    rng = random.Random(seed)
    years = [0, 4, 100, 400, 1900, 2000, 2019, 2020, 2024, 9999] + [
        rng.randint(0, 9999) for _ in range(40)
    ]
    return [(y, m, d) for y in years for m in range(0, 14) for d in (0, 1, 28, 29, 30, 31, 32)]


def test_numeric_dates_agree_with_local_date(models: ResolvedModels) -> None:
    ok = fragment(models, "GD_DATE_ABSOLUTE_OK")
    for y, m, d in date_samples(24):
        for text in (f"{y}-{m:02}-{d:02}", f"{y:04}/{m}/{d}"):
            assert (ok.fullmatch(text) is not None) is is_valid(y, m, d), text


def test_named_dates_agree_with_local_date(models: ResolvedModels) -> None:
    ok = fragment(models, "GD_DATE_ABSOLUTE_OK")
    for y, m, d in date_samples(25):
        if not 1 <= m <= 12:
            continue
        name = MONTHS[m - 1]
        for text in (f"{d} {name.upper()}uary {y}", f"{d}th of {name} {y}", f"{name}. {d}, {y}"):
            assert (ok.fullmatch(text) is not None) is is_valid(y, m, d), text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2020-01-1_", False),
        ("2_20-01-01", False),
        ("D+0002147483647", True),
        ("d+2147483648", False),
        ("D+_", False),
        ("12 days after start", True),
        ("1 day after start", True),
        ("2147483648 days after start", False),
        ("2020-01-01", True),
        ("D+5", True),
    ],
)
def test_any_date_fragment(models: ResolvedModels, text: str, expected: bool) -> None:
    assert (fragment(models, "GD_DATE_ANY_OK").fullmatch(text) is not None) is expected


def test_counts_agree_with_java_int_bounds(models: ResolvedModels) -> None:
    rng = random.Random(26)
    numbers = [JAVA_INT_MAX, JAVA_INT_MAX + 1, 0, 10**10] + [
        rng.randint(0, 10**12) for _ in range(2000)
    ]
    ok = fragment(models, "GD_DATE_ANY_OK")
    for n in numbers:
        assert (ok.fullmatch(f"D+{n}") is not None) is (n <= JAVA_INT_MAX), n


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("[A] #red", True),
        ("[A] #RED/#00f", True),
        ("[A] #a/automatic", True),
        ("[A] #ff00ff80", True),
        ("[A] #transparent", True),
        ("[A] #ab", False),
        ("[A] #zzz", False),
        ("[A] #red/#ffff", False),
        ("[A] #redé", False),
    ],
)
def test_color_task_narrowing(gantt: ResolvedModel, text: str, expected: bool) -> None:
    rule = compile_part(entry(gantt, TASKS, "CommandColorTask")["parts"])
    assert (rule.fullmatch(text) is not None) is expected


# --- fixtures -------------------------------------------------------------------------


def fixtures(group: str) -> list[Path]:
    return sorted((FIXTURES / group).glob("*.puml"))


def header(path: Path) -> dict[str, str]:
    found = (HEADER.match(line) for line in path.read_text(encoding="utf-8").splitlines())
    return {m["key"]: m["value"] for m in found if m}


def fixture_commands(path: Path) -> list[str]:
    return [c.strip() for c in header(path)["gantt"].split(",")]


def rel(path: Path) -> str:
    return path.relative_to(FIXTURES).as_posix()


def restricted(models: ResolvedModels, path: Path) -> Any:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    return accepts(models, block, raw=True, start_map=START_MAP)


@pytest.mark.parametrize("path", fixtures(POS), ids=rel)
def test_pos_fixture_is_accepted(models: ResolvedModels, path: Path) -> None:
    verdict = restricted(models, path)
    assert verdict["accepted"], verdict["first_failure"]
    assert (verdict["diagram"], verdict["model"]) == (DIAGRAM, GANTT_ID)


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
def test_pos_fixture_is_gantt_with_full_dispatch(models: ResolvedModels, path: Path) -> None:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    verdict = accepts(models, block, raw=True)
    assert (verdict["accepted"], verdict["diagram"]) == (True, DIAGRAM)


def test_every_fixture_names_known_commands(models: ResolvedModels) -> None:
    known = set(commands(generated(models)))
    for path in fixtures(POS) + fixtures(NEG) + fixtures(GAP):
        assert set(fixture_commands(path)) <= known, rel(path)


@pytest.mark.parametrize("group", [POS, NEG])
def test_every_gantt_command_has_a_fixture(models: ResolvedModels, group: str) -> None:
    covered = {c for path in fixtures(group) for c in fixture_commands(path)}
    assert set(gantt_commands(models)) <= covered


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


# --- sentences (T25: gantt-sentences*) ------------------------------------------------

NGC = "net.sourceforge.plantuml.gantt.command.NaturalGanttCommand"
# GanttDiagramFactory.java:112-122, in registration order; True = has an Invalid reject.
SUBJECTS = {
    "Gantt": True, "Today": True, "Task": True, "Resource": True, "DaysAsDates": True,
    "DayOfWeek": False, "DayAsDate": True, "Separator": True, "WorkingHours": False,
}  # fmt: skip
SENTENCE_FIXTURES = FIXTURES / "sentences"
HEAD_SAMPLES = ["it lasts 2 days", "[A] lasts 5 days", "Project starts 2020-01-01"]


def sentence_ids() -> list[str]:
    out = []
    for name, invalid in SUBJECTS.items():
        out += [f"NaturalGantt{name}Invalid"] * invalid
        out += ["NaturalGanttTaskNeedsStart"] * (name == "Task")
        out += [f"NaturalGantt{name}", f"NaturalGantt{name}Unmatched"]
    return out


@pytest.mark.parametrize("context", BODY_CONTEXTS)
def test_sentences_precede_the_first_gantt_command(gantt: ResolvedModel, context: str) -> None:
    rest = commands(spliced(gantt, context))
    wanted = sentence_ids()
    end = rest.index(FIRST_GANTT_COMMAND)
    assert rest[end - len(wanted) : end] == wanted
    for item in spliced(gantt, context)[end - len(wanted) : end]:
        assert item.get("reject", False) is not (
            item["command"]
            in [f"NaturalGantt{n}" for n in SUBJECTS] + ["NaturalGanttTaskNeedsStart"]
        )


def test_each_sentence_command_has_an_accept_and_an_unmatched_rule(gantt: ResolvedModel) -> None:
    cited = [e for e in spliced(gantt, TASKS) if e["provenance"]["class"] == NGC]
    assert len(cited) == 2 * len(SUBJECTS)


def test_sentence_heads_carry_their_state(gantt: ResolvedModel) -> None:
    assert entry(gantt, MAIN, "GanttFirstTaskSentence")["set"] == TASKS
    assert entry(gantt, MAIN, "GanttItWithoutTask")["reject"] is True
    for context in (TASKS, GROUP_1, GROUP):
        assert entry(gantt, context, "GanttProjectStartsAfterTask")["reject"] is True


@pytest.mark.parametrize("context", BODY_CONTEXTS)
def test_no_earlier_command_takes_a_sentence_head_line(gantt: ResolvedModel, context: str) -> None:
    rest = spliced(gantt, context)
    earlier = rest[: commands(rest).index(sentence_ids()[0])]
    for sample in HEAD_SAMPLES:
        assert not [e["command"] for e in earlier if compile_part(e["parts"]).fullmatch(sample)]


def bad(models: ResolvedModels, name: str, text: str) -> bool:
    return compile_part(models["gantt-sentences-bad"].variables[name]).fullmatch(text) is not None


def test_bad_number_agrees_with_parse_int(models: ResolvedModels) -> None:
    rng = random.Random(27)
    numbers = [JAVA_INT_MAX, JAVA_INT_MAX + 1, 0] + [rng.randint(0, 10**12) for _ in range(2000)]
    for n in numbers:
        for text in (str(n), f"00{n}"):
            assert bad(models, "GB_BAD_NUM", text) is (n > JAVA_INT_MAX), text
    assert bad(models, "GB_BAD_NUM", "1_2") and bad(models, "GB_BAD_NUM", "_")


def test_not_leap_and_bad_dates_agree_with_local_date(models: ResolvedModels) -> None:
    for year in range(0, 10000, 7):
        assert bad(models, "GB_YEAR_NOT_LEAP", str(year)) is not is_leap(year), year
    for y, m, d in date_samples(28):
        text = f"{y}-{m:02}-{d:02}"
        assert bad(models, "GB_DATE_B_BAD", text) is not is_valid(y, m, d), text
    assert bad(models, "GB_DATE_B_BAD", "2020-1_-01")


def resource_ok(content: str) -> bool:
    """GanttDiagram.affectResource (GanttDiagram.java:378-393) on one `{...}` text."""
    text = content.strip(" \t")
    if not text:
        return True
    found = re.search(r"([^:]+)(:([0-9]+))?", text)
    return found is not None and (found[3] is None or 0 < int(found[3]) <= JAVA_INT_MAX)


def test_bad_resource_agrees_with_affect_resource(models: ResolvedModels) -> None:
    rng = random.Random(29)
    for _ in range(3000):
        content = "".join(rng.choice(" ::0079R") for _ in range(rng.randint(1, 6)))
        assert bad(models, "GB_RESOURCE_BAD", f"{{{content}}}") is not resource_ok(content), content
    assert bad(models, "GB_RESOURCE_BAD", "{R:99999999999}")


def sentence_fixtures(group: str) -> list[Path]:
    return sorted((SENTENCE_FIXTURES / group).glob("*.puml"))


def sentence_rel(path: Path) -> str:
    return path.relative_to(SENTENCE_FIXTURES).as_posix()


def jar_accepts(path: Path) -> bool:
    if path.parent.name in (POS, NEG):
        return path.parent.name == POS
    return header(path)["jar"] == "accepted"


def sentence_params() -> list[Any]:
    out = [
        pytest.param(p, id=sentence_rel(p)) for p in sentence_fixtures(POS) + sentence_fixtures(NEG)
    ]
    for p in sentence_fixtures(GAP):
        mark = pytest.mark.xfail(strict=True, reason=header(p)["gap"])
        out.append(pytest.param(p, id=sentence_rel(p), marks=mark))
    return out


@pytest.mark.parametrize("path", sentence_params())
def test_sentence_fixture_verdict(models: ResolvedModels, path: Path) -> None:
    verdict = restricted(models, path)
    assert verdict["accepted"] is jar_accepts(path), verdict["first_failure"]


@pytest.mark.parametrize("group", [POS, NEG])
def test_every_subject_has_a_sentence_fixture(group: str) -> None:
    named = {c for p in sentence_fixtures(group) for c in fixture_commands(p)}
    assert {n for n in SUBJECTS if [c for c in named if c.startswith(f"NaturalGantt{n}")]} == set(
        SUBJECTS
    )


@pytest.mark.corpus
def test_sentence_fixture_verdicts_equal_the_oracle() -> None:
    from tools.validate.oracle import oracle_verdicts

    paths = [p for g in (POS, NEG, GAP) for p in sentence_fixtures(g)]
    verdicts = oracle_verdicts(paths)
    for path in paths:
        (block,) = verdicts[str(path)]
        assert block["accepted"] is jar_accepts(path), sentence_rel(path)


# --- final check: separators and groups need a real task (diagram flags) -------------

NEEDS = {"CommandSeparator", "GanttFirstTaskBySeparator", "GanttFirstGroup", "GanttGroupAtRoot",
         "GanttGroupInFirstGroup", "GanttGroupInGroup"}  # fmt: skip
GIVES = {
    "CommandGanttArrow2",
    "GanttFirstTaskByArrow",
    "NaturalGanttTask",
    "GanttFirstTaskSentence",
    "NaturalGanttTaskNeedsStart",
    "GanttFirstTaskSentenceNeedsStart",
}
NEEDS_START = {"NaturalGanttTaskNeedsStart", "GanttFirstTaskSentenceNeedsStart"}


@pytest.mark.parametrize("context", BODY_CONTEXTS)
def test_real_task_flag(gantt: ResolvedModel, context: str) -> None:
    entries = gantt.contexts[context]
    assert {e["command"] for e in entries if e.get("needs") == "real_task"} <= NEEDS
    assert {e["command"] for e in entries if e.get("gives") == "real_task"} <= GIVES
    for e in entries:
        if e["command"] in NEEDS | GIVES:
            assert e.get("needs" if e["command"] in NEEDS else "gives") == "real_task", e["command"]


@pytest.mark.parametrize("context", BODY_CONTEXTS)
def test_project_start_flag(gantt: ResolvedModel, context: str) -> None:
    entries = gantt.contexts[context]
    assert {e["command"] for e in entries if e.get("gives") == "project_start"} == {
        "NaturalGanttGantt"
    }
    needing = {e["command"] for e in entries if e.get("needs") == "project_start"}
    assert needing == NEEDS_START & set(commands(entries))
    assert all(e.get("emit") is False for e in entries if e["command"] in needing)


@pytest.mark.parametrize(
    ("line", "needs"),
    [
        ("[A] starts 2020-01-03", True),
        ("[A] lasts 2 days and ends the 3rd of jan 2020", True),
        ("[A] starts 2020-01-03 10:00 and is colored in red", True),
        ("[A] starts D+3", False),
        ("[A] starts at [B]'s end", False),
        ("[A] happens 2020-01-03", False),
        ("[A] starts 2020-01-03 10:00 and foo", False),
        ("[B] starts 20 days after [A]'s end and lasts 3 days", False),
        ("[B] starts  2 days after [A]'s end", False),
        ("[A] starts   D+3", False),
        ("[A] starts on the 2020-01-03", True),
    ],
)
def test_needs_start_shape(gantt: ResolvedModel, line: str, needs: bool) -> None:
    rule = compile_part(entry(gantt, TASKS, "NaturalGanttTaskNeedsStart")["parts"])
    assert (rule.fullmatch(line) is not None) is needs


@pytest.mark.parametrize(
    "text",
    [
        "at [A]'s end", "with [A]'s start", "after [A]'s end", "2 days after [A]'s end",
        "3 working weeks before [B]'s start", "1 day and 2 weeks after [A]'s end", "  [A]'s end",
        "the 3 days after start", "d+5", "on 12 days after start", "2020-01-01", "20 days after",
        "at [A] end", "3 days before start",
    ],
)  # fmt: skip
def test_not_before_or_relative_is_the_check_shapes(models: ResolvedModels, text: str) -> None:
    phrases = models["gantt-sentences-phrases"].variables
    lang = models["gantt-lang"].variables
    before = compile_part(lang["COMPLEMENT_BEFORE_OR_AFTER_OR_AT_TASK_START_OR_END"])
    relative = compile_part({"seq": [phrases["GS_IGN_2"], lang["COMPLEMENT_DATE_ONLY_RELATIVE"]]})
    checks = any(p.match(text.lstrip(" ")) for p in (before, relative))
    guard = compile_part(phrases["GS_NOT_BEFORE_OR_RELATIVE"])
    assert (guard.match(text) is None) is checks, text
