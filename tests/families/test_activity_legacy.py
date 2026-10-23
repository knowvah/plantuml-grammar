"""Legacy activity diagrams (T22, ``model/diagrams/activity-legacy*.yaml``).

``activity-legacy`` is the top model of ``ActivityDiagramFactory``. It includes the
generated model, ``common`` and the shared ``activity-legacy-parts`` (structured copies of
generated rules), and defines one context per diagram state, each running the whole
generated command list between head and tail entries (see the model header).

Fixtures (``tests/fixtures/activity-legacy``), one block each, with a header::

    ' activity-legacy: RuleA, RuleB   rule ids the fixture exercises
    ' gap: <reason>                   gap/ only: why the model cannot reproduce the jar

``pos/`` is accepted as ACTIVITY and ``neg/`` and ``gap/`` are rejected by the jar
(``corpus`` test). The interpreter runs each fixture raw with dispatch restricted to
ActivityDiagramFactory; neg fixtures use legacy-only syntax so that every factory rejects.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from tools.interp import accepts
from tools.interp.source import split_blocks
from tools.model import Model, ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve, top_models

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO / "model"
FIXTURES = REPO / "tests" / "fixtures" / "activity-legacy"
POS, NEG, GAP = "pos", "neg", "gap"
MODEL_ID = "activity-legacy"
PARTS_ID = "activity-legacy-parts"
GEN_ID = "gen-activity-diagram"
FACTORY = "ActivityDiagramFactory"
DIAGRAM = "ACTIVITY"
MAIN = "main"
START_MAP = {"uml": [FACTORY]}
UPSTREAM_PREFIX = "src/main/java/"
HEADER = re.compile(r"^' (?P<key>activity-legacy|gap): (?P<value>.+)$")
COMMAND, PROVENANCE = "command", "provenance"
REMOVED = ("UBrexCommandEndPartition", "UBrexCommandElse", "UBrexCommandEndif")
ROOT, IF_, IF_ROOT = "activity_root", "activity_if", "activity_if_root"
GROUP, GROUP_ROOT = "activity_group", "activity_group_root"
ORPHAN, ORPHAN_IF = "activity_orphan", "activity_orphan_if"
STATE_CONTEXTS = (MAIN, ROOT, IF_, IF_ROOT, GROUP, GROUP_ROOT, ORPHAN, ORPHAN_IF)
NO_IF = {"ActivityElseWithoutIf": ("reject", None), "ActivityEndifWithoutIf": ("reject", None)}
# Context -> {tail rule: (transition key, target)}; `None` = no transition.
ACCEPT, REJECT = ("accept", None), ("reject", None)
TAILS: dict[str, dict[str, tuple[str, str | None]]] = {
    MAIN: {**NO_IF, "ActivityEndGroupOrphan": ("set", ORPHAN)},
    ROOT: {**NO_IF, "ActivityEndGroupOrphan": ("set", ORPHAN)},
    IF_: {
        "ActivityElse": ACCEPT,
        "ActivityEndif": ("pop", None),
        "ActivityEndGroupLenient": ACCEPT,
    },
    IF_ROOT: {
        "ActivityElse": ACCEPT,
        "ActivityEndifRoot": ("set", ROOT),
        "ActivityEndGroupOrphanIf": ("set", ORPHAN_IF),
    },
    GROUP: {
        "ActivityElse": ACCEPT,
        "ActivityEndifLenient": ACCEPT,
        "ActivityEndGroup": ("pop", None),
    },
    GROUP_ROOT: {**NO_IF, "ActivityEndGroupRoot": ("set", ROOT)},
    ORPHAN: NO_IF,
    ORPHAN_IF: {"ActivityElse": ACCEPT, "ActivityEndifOrphan": ("set", ORPHAN)},
}
FRESH_HEADS = [
    ("ActivityPartitionFirst", ("set", GROUP_ROOT)),
    ("ActivityLinkLongNoSource", REJECT),
    ("ActivityLinkLongFirst", ("set", ROOT)),
    ("ActivityNoteFirst", ("set", ROOT)),
    ("ActivityNoteLongFirst", ("set", ROOT)),
    ("ActivityNoteOnLinkFirst", REJECT),
    ("ActivityNoteOnLinkLongFirst", REJECT),
    ("ActivityIfNoSource", REJECT),
    ("ActivityIfFirst", ("set", IF_ROOT)),
    ("ActivityLinkNoSource", REJECT),
    ("ActivityLinkFirstToBlock", ("set", GROUP_ROOT)),
    ("ActivityLinkFirst", ("set", ROOT)),
]


@cache
def raw_models() -> dict[str, Model]:
    return load_dir(MODEL_DIR)


@cache
def models() -> ResolvedModels:
    return resolve(raw_models())


def entries(context: str) -> list[dict[str, Any]]:
    return list(models()[MODEL_ID].contexts[context])


def command_ids(context: str) -> list[str]:
    return [str(e[COMMAND]) for e in entries(context)]


def generated_ids() -> list[str]:
    return [str(e[COMMAND]) for e in models()[GEN_ID].contexts[MAIN]]


def gen_entry(command: str) -> dict[str, Any]:
    return next(e for e in models()[GEN_ID].contexts[MAIN] if e[COMMAND] == command)


def entry(context: str, command: str) -> dict[str, Any]:
    return next(e for e in entries(context) if e[COMMAND] == command)


def transition(e: dict[str, Any]) -> tuple[str, str | None]:
    if e.get("reject"):
        return REJECT
    for key in ("push", "set"):
        if key in e:
            return (key, str(e[key]))
    return ("pop", None) if e.get("pop") else ACCEPT


# --- model shape -----------------------------------------------------------------------


def test_activity_legacy_is_the_top_model_of_the_factory() -> None:
    model = models()[MODEL_ID]
    assert top_models(models())[FACTORY] == MODEL_ID
    assert (model.layer, model.diagram, model.factory) == ("diagram", DIAGRAM, FACTORY)
    assert set(model.includes) >= {GEN_ID, "common", PARTS_ID}
    assert raw_models()[PARTS_ID].layer == "shared"


@pytest.mark.parametrize("context", STATE_CONTEXTS)
def test_every_state_runs_the_generated_list_in_upstream_order(context: str) -> None:
    kept = [c for c in generated_ids() if c not in REMOVED]
    present = [c for c in command_ids(context) if c in set(generated_ids())]
    assert present == kept


@pytest.mark.parametrize("context", STATE_CONTEXTS)
def test_tails_follow_the_generated_list_with_their_transitions(context: str) -> None:
    ids = command_ids(context)
    last_generated = max(i for i, c in enumerate(ids) if c in set(generated_ids()))
    tail = {c: transition(entry(context, c)) for c in ids[last_generated + 1 :]}
    assert tail == TAILS[context]


def test_fresh_heads_precede_the_generated_list_in_upstream_order() -> None:
    ids = command_ids(MAIN)
    heads = [(c, transition(entry(MAIN, c))) for c in ids[: len(FRESH_HEADS)]]
    assert heads == FRESH_HEADS
    assert ids[len(FRESH_HEADS)] == generated_ids()[0]


@pytest.mark.parametrize("context", [ORPHAN, ORPHAN_IF])
def test_orphan_rejects_unsafe_lines_before_the_generated_list(context: str) -> None:
    assert command_ids(context)[0] == "ActivityOrphanUnsafe"
    assert transition(entry(context, "ActivityOrphanUnsafe")) == REJECT


@pytest.mark.parametrize("context", STATE_CONTEXTS)
def test_openers_push_in_every_state(context: str) -> None:
    ids = command_ids(context)
    assert transition(entry(context, "UBrexCommandIf")) == ("push", IF_)
    assert transition(entry(context, "UBrexCommandPartition")) == ("push", GROUP)
    assert transition(entry(context, "ActivityLinkToBlock")) == ("push", GROUP)
    assert ids.index("ActivityLinkToBlock") == ids.index("CommandLinkActivity") - 1


def family_entries() -> list[dict[str, Any]]:
    return [e for c in STATE_CONTEXTS for e in entries(c) if str(e[COMMAND]).startswith("Activity")]


def test_hand_written_entries_cite_an_upstream_file_and_another_class() -> None:
    gen = set(generated_ids())
    assert len(family_entries()) > len(FRESH_HEADS)
    for e in family_entries():
        prov = e[PROVENANCE]
        assert str(prov["file"]).startswith(UPSTREAM_PREFIX), e[COMMAND]
        assert int(prov["line"]) > 0, e[COMMAND]
        assert "refined_by" not in e, e[COMMAND]
        assert str(prov["class"]).rsplit(".", 1)[-1] not in gen, e[COMMAND]


# --- structured copies equal the generated parts ------------------------------------------


def flat(part: dict[str, Any]) -> dict[str, Any]:
    """Splice nested ``seq`` into their parent ``seq`` and recurse."""
    if "seq" in part:
        items: list[dict[str, Any]] = []
        for child in (flat(p) for p in part["seq"]):
            items.extend(child["seq"] if "seq" in child else [child])
        return {"seq": items}
    if "alt" in part:
        return {"alt": [flat(p) for p in part["alt"]]}
    for key in ("opt", "star", "plus"):
        if key in part:
            return {key: flat(part[key])}
    return dict(part)


def var(name: str) -> dict[str, Any]:
    return dict(models()[MODEL_ID].variables[name])


def seq(*parts: dict[str, Any]) -> dict[str, Any]:
    return flat({"seq": list(parts)})


def test_link_copies_equal_the_generated_link() -> None:
    generated = flat(gen_entry("CommandLinkActivity")["parts"])
    assert seq({"opt": var("AL_SOURCE")}, var("AL_LINK_NO_SOURCE")) == generated
    assert flat(var("AL_LINK_WITH_SOURCE")) == seq(var("AL_SOURCE"), var("AL_LINK_NO_SOURCE"))
    target = generated["seq"].index(flat(var("AL_TARGET")))
    block = dict(generated, seq=list(generated["seq"]))
    block["seq"][target] = var("AL_TARGET_BLOCK")
    assert flat(var("AL_LINK_TO_BLOCK")) == block
    assert flat(var("AL_LINK_WITH_SOURCE_TO_BLOCK")) == seq(
        var("AL_SOURCE"), {"seq": block["seq"][1:]}
    )


def test_long_link_copies_equal_the_generated_long_link() -> None:
    generated = gen_entry("CommandLinkLongActivity")
    assert seq({"opt": var("AL_SOURCE")}, var("AL_LONG_NO_SOURCE")) == flat(generated["parts"])
    assert flat(var("AL_LONG_WITH_SOURCE")) == seq(var("AL_SOURCE"), var("AL_LONG_NO_SOURCE"))
    assert var("AL_LONG_END") == generated["end"]


def test_if_copies_equal_the_generated_if() -> None:
    alternatives = gen_entry("UBrexCommandIf")["parts"]["alt"]
    simple = flat(var("AL_IF_NO_SOURCE"))
    assert flat(alternatives[0]) == simple
    sourced = [seq(head, simple) for head in var("AL_IF_SOURCE")["alt"]]
    assert sourced == [flat(a) for a in alternatives[1:]]
    assert flat(var("AL_IF_WITH_SOURCE")) == seq(var("AL_IF_SOURCE"), simple)


@pytest.mark.parametrize(
    ("variable", "command"),
    [
        ("AL_PARTITION", "UBrexCommandPartition"),
        ("AL_NOTE", "CommandFactoryNoteActivity_2"),
        ("AL_NOTE_HEAD", "CommandFactoryNoteActivity_1"),
        ("AL_NOTE_ON_LINK", "CommandFactoryNoteOnLink_2"),
        ("AL_NOTE_ON_LINK_HEAD", "CommandFactoryNoteOnLink_1"),
    ],
)
def test_partition_and_note_copies_equal_the_generated_rules(variable: str, command: str) -> None:
    assert flat(var(variable)) == flat(gen_entry(command)["parts"])


def test_note_end_equals_the_generated_end() -> None:
    assert var("AL_NOTE_END") == gen_entry("CommandFactoryNoteActivity_1")["end"]


# --- fixtures ----------------------------------------------------------------------------


def fixtures(group: str) -> list[Path]:
    return sorted((FIXTURES / group).glob("*.puml"))


def rel(path: Path) -> str:
    return f"{path.parent.name}/{path.stem}"


def header(path: Path) -> dict[str, str]:
    found = (HEADER.match(line) for line in path.read_text(encoding="utf-8").splitlines())
    return {m["key"]: m["value"] for m in found if m}


def verdict(path: Path) -> bool:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    return bool(accepts(models(), block, raw=True, start_map=START_MAP)["accepted"])


def body_verdict(body: str) -> bool:
    block = f"@startuml\n{body}\n@enduml\n"
    return bool(accepts(models(), block, start_map=START_MAP)["accepted"])


@pytest.mark.parametrize("path", fixtures(POS), ids=rel)
def test_pos_fixture_is_accepted(path: Path) -> None:
    assert verdict(path) is True


@pytest.mark.parametrize("path", fixtures(NEG), ids=rel)
def test_neg_fixture_is_rejected(path: Path) -> None:
    assert verdict(path) is False


def gap_params() -> list[Any]:
    return [
        pytest.param(p, id=rel(p), marks=pytest.mark.xfail(strict=True, reason=header(p)["gap"]))
        for p in fixtures(GAP)
    ]


@pytest.mark.parametrize("path", gap_params())
def test_gap_fixture_matches_the_jar(path: Path) -> None:
    assert verdict(path) is False


def test_every_fixture_names_rules_of_the_model() -> None:
    known = {c for ctx in models()[MODEL_ID].contexts for c in command_ids(ctx)}
    for path in fixtures(POS) + fixtures(NEG) + fixtures(GAP):
        named = {c.strip() for c in header(path)["activity-legacy"].split(",")}
        assert named <= known, rel(path)


def test_every_reject_entry_has_a_neg_fixture() -> None:
    errors = raw_models()["common-errors"]
    common = {str(e[COMMAND]) for es in errors.insert_after.values() for e in es}
    rejects = {str(e[COMMAND]) for c in STATE_CONTEXTS for e in entries(c) if e.get("reject")}
    covered = {c.strip() for p in fixtures(NEG) for c in header(p)["activity-legacy"].split(",")}
    assert rejects - common <= covered


# --- inline cases (interpreter here, jar in the corpus test) -------------------------

# (body, accepted by the jar's ActivityDiagramFactory and by the jar as a whole).
INLINE_CASES = [
    ("(*) --> iff x then\n--> A\nendif", False),
    ("(*) --> A\n--> if x then\n--> B\nelse\n--> C\nendif\nendif", False),
    ("(*) --> A\nA --> {\n--> B\n}\n}\n}", False),
    ("(*) --> A\nA --> {\n--> B\n}\n}\ntitle T", True),
    ("partition P {\npartition Q {\n(*) --> A\n}\n}\n--> B", True),
    ("(*) --> if x then\nif y then\n--> A\nendif\nendif\n--> (*)", True),
    ("(*) --> A\n}\nhide-class A\nleft to right direction", True),
    ("(*) --> A\n}\nendif", False),
    ("(*) --> if x then\n}\nendif\nelse", False),
    ("(*) --> if x then\n}\nelse\nendif\ntitle T", True),
    ("(*) --> A\nscale 0", False),
]


@pytest.mark.parametrize(("body", "accepted"), INLINE_CASES)
def test_inline_case(body: str, accepted: bool) -> None:
    assert body_verdict(body) is accepted


# --- corpus: oracle verdicts ---------------------------------------------------------


@pytest.mark.corpus
def test_fixture_verdicts_equal_the_oracle() -> None:
    from tools.validate.oracle import oracle_verdicts

    paths = fixtures(POS) + fixtures(NEG) + fixtures(GAP)
    verdicts = oracle_verdicts(paths)
    for path in paths:
        (block,) = verdicts[str(path)]
        assert block["accepted"] is (path.parent.name == POS), rel(path)
        if path.parent.name == POS:
            assert block["diagram_type"] == DIAGRAM, rel(path)


@pytest.mark.corpus
def test_inline_cases_equal_the_oracle(tmp_path: Path) -> None:
    from tools.validate.oracle import oracle_verdicts

    paths = []
    for index, (body, _) in enumerate(INLINE_CASES):
        path = tmp_path / f"case{index}.puml"
        path.write_text(f"@startuml\n{body}\n@enduml\n", encoding="utf-8")
        paths.append(path)
    verdicts = oracle_verdicts(paths)
    for path, (body, accepted) in zip(paths, INLINE_CASES, strict=True):
        assert verdicts[str(path)][0]["accepted"] is accepted, body
