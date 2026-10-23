"""State diagrams (T20, ``model/diagrams/state.yaml``, ``id: state``).

``state`` is the top model of ``StateDiagramFactory``. It includes the generated model
and ``common`` and defines one context per position in the group stack, each running
the whole generated command list after a few head entries (see the model header):
``main`` (the root), ``main_concurrent`` (a concurrent region opened at the root) and
``state_body`` (inside a composite state or a frame).

Fixtures (``tests/fixtures/state``), one block each, with a header before ``@start``::

    ' state: RuleA, RuleB      rule ids the fixture exercises
    ' jar: accepted            gap/ only, when the jar accepts (default: rejected)
    ' gap: <reason>            gap/ only: why the model cannot reproduce the jar

``pos/`` is accepted (as STATE) and ``neg/`` rejected by the jar (``corpus`` test). The
interpreter runs each fixture raw with dispatch restricted to StateDiagramFactory.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
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
FIXTURES = REPO / "tests" / "fixtures" / "state"
POS, NEG, GAP = "pos", "neg", "gap"
STATE_ID = "state"
GEN_ID = "gen-state-diagram"
FACTORY = "StateDiagramFactory"
DIAGRAM = "STATE"
MAIN, MAIN_CONCURRENT, BODY = "main", "main_concurrent", "state_body"
CONTEXTS = (MAIN, MAIN_CONCURRENT, BODY)
REMOVED = {"CommandEndState"}
START_MAP = {"uml": [FACTORY]}
JAR_ACCEPTED = "accepted"
UPSTREAM_PREFIX = "src/main/java/"
HEADER = re.compile(r"^' (?P<key>state|jar|gap): (?P<value>.+)$")
COMMAND, PROVENANCE = "command", "provenance"
POSITION = "ST_POSITION_LINE"


@cache
def raw_models() -> dict[str, Model]:
    return load_dir(MODEL_DIR)


@cache
def models() -> ResolvedModels:
    return resolve(raw_models())


def entries(context: str) -> list[dict[str, Any]]:
    return list(models()[STATE_ID].contexts[context])


def command_ids(context: str) -> list[str]:
    return [str(e[COMMAND]) for e in entries(context)]


def entry(context: str, command: str) -> dict[str, Any]:
    return next(e for e in entries(context) if e[COMMAND] == command)


def gen_entry(command: str) -> dict[str, Any]:
    return next(e for e in models()[GEN_ID].contexts[MAIN] if e[COMMAND] == command)


def fixtures(group: str) -> list[Path]:
    return sorted((FIXTURES / group).glob("*.puml"))


def rel(path: Path) -> str:
    return f"{path.parent.name}/{path.stem}"


def header(path: Path) -> dict[str, str]:
    found = (HEADER.match(line) for line in path.read_text(encoding="utf-8").splitlines())
    return {m["key"]: m["value"] for m in found if m}


def jar_accepts(path: Path) -> bool:
    if path.parent.name == GAP:
        return header(path).get("jar") == JAR_ACCEPTED
    return path.parent.name == POS


def state_verdict(path: Path) -> bool:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    return bool(accepts(models(), block, raw=True, start_map=START_MAP)["accepted"])


def body_verdict(body: str) -> bool:
    block = f"@startuml\n{body}\n@enduml\n"
    return bool(accepts(models(), block, start_map=START_MAP)["accepted"])


# --- model shape -----------------------------------------------------------------------


def test_state_is_the_top_model_of_the_state_factory() -> None:
    model = models()[STATE_ID]
    assert top_models(models())[FACTORY] == STATE_ID
    assert (model.layer, model.diagram, model.factory) == ("diagram", DIAGRAM, FACTORY)
    assert set(model.includes) >= {GEN_ID, "common"}


@pytest.mark.parametrize("context", CONTEXTS)
def test_every_context_runs_the_generated_list_in_upstream_order(context: str) -> None:
    generated = [str(e[COMMAND]) for e in models()[GEN_ID].contexts[MAIN]]
    present = [c for c in command_ids(context) if c in set(generated)]
    assert present == [c for c in generated if c not in REMOVED]


@pytest.mark.parametrize("command", ["CommandCreatePackageState", "CommandCreatePackage2"])
def test_composites_enter_the_state_body_without_requiring_a_close(command: str) -> None:
    found = entry(MAIN, command)
    assert (found["push"], found.get("require_pop")) == (BODY, None)
    assert found["refined_by"] == STATE_ID


@pytest.mark.parametrize(
    ("context", "closer", "transition"),
    [
        (MAIN, "StateEndAtRoot", {"reject": True}),
        (MAIN_CONCURRENT, "StateEndConcurrentRoot", {"reject": True}),
        (BODY, "StateEnd", {"pop": True}),
    ],
)
def test_each_context_has_its_own_closer_at_the_head(
    context: str, closer: str, transition: dict[str, bool]
) -> None:
    ids = command_ids(context)
    found = entry(context, closer)
    assert ids.index(closer) < ids.index("CommandFootboxIgnored")
    assert {k: found.get(k) for k in transition} == transition
    assert found["parts"] == gen_entry("CommandEndState")["parts"]


def test_a_region_at_the_root_switches_to_the_concurrent_root_context() -> None:
    found = entry(MAIN, "StateConcurrentAtRoot")
    assert found["set"] == MAIN_CONCURRENT
    assert found["parts"] == gen_entry("CommandConcurrentState")["parts"]
    assert "set" not in entry(MAIN_CONCURRENT, "CommandConcurrentState")


def test_position_stereotypes_are_rejected_at_the_root_only() -> None:
    found = entry(MAIN, "StatePositionStereotypeAtRoot")
    assert found["reject"] is True
    assert found["parts"]["seq"] == [
        models()[STATE_ID].variables[POSITION],
        gen_entry("CommandCreateState")["parts"],
    ]
    for context in (MAIN_CONCURRENT, BODY):
        assert "StatePositionStereotypeAtRoot" not in command_ids(context)


def test_create_state_keeps_the_generated_shape() -> None:
    found = entry(BODY, "CommandCreateState")
    assert found["parts"] == gen_entry("CommandCreateState")["parts"]
    assert "refined_by" not in found


@pytest.mark.parametrize(
    ("line", "position"),
    [
        ("state X <<exitpoint>>", True),
        ("state X <<EntryPoint>> #red : d", True),
        ('state "x y" <<inputPin>>', True),
        ('state X as "x" <<outputpin>>', True),
        ('state "x" as X <<expansionInput>>', True),
        ("state .X $t<<expansionOutput>>", True),
        ("state X <<port>>", True),
        ("state P.X <<exitpoint>>", False),
        ('state "P.X" <<exitpoint>>', False),
        ('state P.X as "x" <<exitpoint>>', False),
        ("state X <<exitpoint>> <<foo>>", False),
        ("state X << exitpoint >>", False),
        ("state X <<portin>>", False),
        ("state X <<choice>>", False),
    ],
)
def test_position_line_recognises_root_failures(line: str, position: bool) -> None:
    lookahead = compile_part(models()[STATE_ID].variables[POSITION])
    assert (lookahead.match(line) is not None) is position


def hand_written() -> Iterator[tuple[str, dict[str, Any]]]:
    """Entries the state model adds (common's inserted rejects belong to T16)."""
    for context in CONTEXTS:
        yield from ((context, e) for e in entries(context) if str(e[COMMAND]).startswith("State"))


HAND_WRITTEN = {
    (MAIN, "StateEndAtRoot"),
    (MAIN, "StateConcurrentAtRoot"),
    (MAIN, "StatePositionStereotypeAtRoot"),
    (MAIN_CONCURRENT, "StateEndConcurrentRoot"),
    (BODY, "StateEnd"),
}


def test_hand_written_entries_cite_an_upstream_file_and_line() -> None:
    seen = set()
    for context, found in hand_written():
        prov = found[PROVENANCE]
        assert str(prov["file"]).startswith(UPSTREAM_PREFIX), found[COMMAND]
        assert int(prov["line"]) > 0, found[COMMAND]
        assert "refined_by" not in found, found[COMMAND]
        seen.add((context, str(found[COMMAND])))
    assert seen == HAND_WRITTEN


# --- fixtures ----------------------------------------------------------------------------


@pytest.mark.parametrize("path", fixtures(POS), ids=rel)
def test_pos_fixture_is_accepted(path: Path) -> None:
    assert state_verdict(path) is True


@pytest.mark.parametrize("path", fixtures(NEG), ids=rel)
def test_neg_fixture_is_rejected(path: Path) -> None:
    assert state_verdict(path) is False


def gap_params() -> list[Any]:
    return [
        pytest.param(p, id=rel(p), marks=pytest.mark.xfail(strict=True, reason=header(p)["gap"]))
        for p in fixtures(GAP)
    ]


@pytest.mark.parametrize("path", gap_params())
def test_gap_fixture_matches_the_jar(path: Path) -> None:
    assert state_verdict(path) is jar_accepts(path)


def test_every_fixture_names_rules_of_the_state_model() -> None:
    known = {c for ctx in models()[STATE_ID].contexts for c in command_ids(ctx)}
    for path in fixtures(POS) + fixtures(NEG) + fixtures(GAP):
        named = {c.strip() for c in header(path)["state"].split(",")}
        assert named <= known, rel(path)


def test_every_reject_entry_has_a_neg_fixture() -> None:
    errors = raw_models()["common-errors"]
    common = {str(e[COMMAND]) for es in errors.insert_after.values() for e in es}
    rejects = {str(e[COMMAND]) for c in CONTEXTS for e in entries(c) if e.get("reject")}
    covered = {c.strip() for p in fixtures(NEG) for c in header(p)["state"].split(",")}
    assert rejects - common == {
        "StateEndAtRoot",
        "StateEndConcurrentRoot",
        "StatePositionStereotypeAtRoot",
    }
    assert rejects - common <= covered


# --- inline cases (interpreter here, jar in the corpus test) -------------------------

# (body, accepted by the jar).
INLINE_CASES = [
    ("state A {\n}\nstate X <<exitpoint>>", False),
    ("state A begin\nend state\nstate X <<inputpin>>", False),
    ("frame F {\n  --\n}\nstate X <<exitpoint>>", False),
    ("frame F {\n  state X <<exitpoint>>\n}", True),
    ("state Z\n--\nstate B {\n}\n}", False),
    ("state Z\n||\n}", False),
    ("state Z\n--\nstate Y\n--\nstate X\n}", False),
    ("state Z\n--\nstate B {\n  --\n  state C\n}\nstate D", True),
    ("state A {\n  state B\n  --\n  state C\nend state\n}", False),
    ("state A {\n  ||\n  state B\n}", True),
    ("state A begin\n  state B\nend  state", False),
    ("state A {}", False),
    ("state X <<exitPoint>> $tag", False),
    ("state A\nnote left of A\n}\nend note", True),
]


@pytest.mark.parametrize(("body", "accepted"), INLINE_CASES)
def test_inline_case(body: str, accepted: bool) -> None:
    assert body_verdict(body) is accepted


# --- corpus: oracle verdicts ----------------------------------------------------------


@pytest.mark.corpus
def test_fixture_verdicts_equal_the_oracle() -> None:
    from tools.validate.oracle import oracle_verdicts

    paths = fixtures(POS) + fixtures(NEG) + fixtures(GAP)
    verdicts = oracle_verdicts(paths)
    for path in paths:
        (block,) = verdicts[str(path)]
        assert block["accepted"] is jar_accepts(path), rel(path)
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
