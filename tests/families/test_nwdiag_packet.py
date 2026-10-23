"""nwdiag and packetdiag (T27, ``model/diagrams/nwdiag-packet-*.yaml``).

``nwdiag-packet-nwdiag`` extends ``gen-nw-diagram`` and ``common``. Its contexts mirror
NwDiagram's stack: ``main`` (empty), ``nw_network`` and ``nw_group``; the generated
openers are replaced by per-state heads (push where upstream accepts, reject where it
fails) and ``}`` pops (a plain line in ``main``).

``nwdiag-packet-packet`` extends ``gen-packet-diagram`` and ``common``. The first field
pushes ``packet_body`` with ``require_pop``, so the interpreter retries it at the end of
the block, where a zero-width first field needs a later field of non-zero width
(PacketDiagram.checkFinalError divides by zero otherwise). ``scale_interval`` is
narrowed to Java int range.

Fixtures (``tests/fixtures/nwdiag-packet``), each with a header before ``@start``::

    ' nwdiag-packet: RuleA, RuleB       rule ids the fixture exercises
    ' gap: <reason>                     gap/ only: why the model cannot reject it

``pos/`` is accepted by the jar as NWDIAG or PACKET, ``neg/`` and ``gap/`` are rejected
(``corpus`` test). Only these factories serve ``@startnwdiag`` and ``@startpacketdiag``.
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
FIXTURES = REPO / "tests" / "fixtures" / "nwdiag-packet"
POS, NEG, GAP = "pos", "neg", "gap"
NW_ID, PK_ID = "nwdiag-packet-nwdiag", "nwdiag-packet-packet"
NW_GEN, PK_GEN, COMMON_ID = "gen-nw-diagram", "gen-packet-diagram", "common"
NW_FACTORY, PK_FACTORY = "NwDiagramFactory", "PacketDiagramFactory"
NW_DIAGRAM, PK_DIAGRAM = "NWDIAG", "PACKET"
MAIN, NETWORK, GROUP, BODY = "main", "nw_network", "nw_group", "packet_body"
UPSTREAM_PREFIX = "src/main/java/net/sourceforge/plantuml/"
HEADER = re.compile(r"^' (?P<key>nwdiag-packet|gap): (?P<value>.+)$")
JAVA_INT_MAX = 2**31 - 1
# NwDiagramFactory.java:65 / PacketDiagramFactory.java:77: first command after the common block.
NW_FIRST, PK_FIRST = "CommandNwDiagInit", "CommandPacketDiagStart"
NW_REMOVED = ("CommandGroup", "CommandNetwork")
# head -> (upstream counterpart, action key, action value, sample line)
NW_HEADS: dict[str, dict[str, tuple[str, str, Any, str]]] = {
    MAIN: {
        "NwDescriptionWithoutOwner": ("CommandProperty", "reject", True, 'description = "x";'),
        "NwCloseNothing": ("CommandEndSomething", "pop", None, "}"),
        "NwGroupOpenAtRoot": ("CommandGroup", "push", GROUP, "group g1 {"),
        "NwNetworkOpenAtRoot": ("CommandNetwork", "push", NETWORK, "network dmz-1.a {"),
    },
    NETWORK: {
        "NwNetworkInNetwork": ("CommandNetwork", "reject", True, "network {"),
        "NwGroupOpenInNetwork": ("CommandGroup", "push", GROUP, "group {"),
    },
    GROUP: {
        "NwGroupInGroup": ("CommandGroup", "reject", True, "GROUP x{"),
        "NwNetworkInGroup": ("CommandNetwork", "reject", True, "network n {"),
    },
}
PK_HEADS = ["PacketFirstField", "PacketZeroWidthRow", "PacketZeroWidthOnly"]
PK_FIELD_SAMPLES = ["0-15: Source Port", "* A [len=0]", "7 x", "106: URG [rotate = 270]"]


@pytest.fixture(scope="module")
def raw_models() -> dict[str, Model]:
    return load_dir(MODEL_DIR)


@pytest.fixture(scope="module")
def models(raw_models: dict[str, Model]) -> ResolvedModels:
    return resolve(raw_models)


def commands(entries: list[dict[str, Any]]) -> list[str]:
    return [e["command"] for e in entries]


def entry(model: ResolvedModel, context: str, command: str) -> dict[str, Any]:
    (found,) = [e for e in model.contexts[context] if e["command"] == command]
    return found


def generated(models: ResolvedModels, gen_id: str) -> list[dict[str, Any]]:
    return models[gen_id].contexts[MAIN]


def generated_entry(models: ResolvedModels, gen_id: str, command: str) -> dict[str, Any]:
    (found,) = [e for e in generated(models, gen_id) if e["command"] == command]
    return found


def family_commands(models: ResolvedModels, gen_id: str, first: str) -> list[str]:
    order = commands(generated(models, gen_id))
    return order[order.index(first) :]


def fullmatch(part: Any, text: str) -> bool:
    return compile_part(part).fullmatch(text) is not None


# --- the models -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mid", "gen_id", "factory", "diagram"),
    [(NW_ID, NW_GEN, NW_FACTORY, NW_DIAGRAM), (PK_ID, PK_GEN, PK_FACTORY, PK_DIAGRAM)],
)
def test_family_model_is_the_top_model_of_its_factory(
    raw_models: dict[str, Model],
    models: ResolvedModels,
    mid: str,
    gen_id: str,
    factory: str,
    diagram: str,
) -> None:
    raw = raw_models[mid]
    assert (raw.layer, raw.diagram, raw.factory) == ("diagram", diagram, factory)
    assert raw.include == [gen_id, COMMON_ID]
    assert top_models(models)[factory] == mid


@pytest.mark.parametrize("context", list(NW_HEADS))
def test_nwdiag_context_is_heads_then_the_generated_order(
    models: ResolvedModels, context: str
) -> None:
    got = commands(models[NW_ID].contexts[context])
    heads = list(NW_HEADS[context])
    assert got[: len(heads)] == heads
    wanted = [c for c in commands(generated(models, NW_GEN)) if c not in NW_REMOVED]
    rest = got[len(heads) :]
    assert [c for c in rest if c in set(wanted)] == wanted
    assert not set(heads) & set(rest)


@pytest.mark.parametrize("context", list(NW_HEADS))
def test_nwdiag_heads_carry_their_action(models: ResolvedModels, context: str) -> None:
    for head, (_, key, value, _) in NW_HEADS[context].items():
        got = entry(models[NW_ID], context, head)
        if key == "pop":
            assert not {"push", "pop", "set", "reject"} & set(got), head
        else:
            assert got[key] == value, head


@pytest.mark.parametrize("context", list(NW_HEADS))
def test_nwdiag_closer_pops_and_openers_are_heads_only(
    models: ResolvedModels, context: str
) -> None:
    assert entry(models[NW_ID], context, "CommandEndSomething")["pop"] is True
    assert not set(NW_REMOVED) & set(commands(models[NW_ID].contexts[context]))


@pytest.mark.parametrize("context", list(NW_HEADS))
def test_nwdiag_heads_match_what_their_counterpart_matches(
    models: ResolvedModels, context: str
) -> None:
    near_misses = ["group", "group a b {", "network a b {", "description x", "} x", "};"]
    for head, (counterpart, _, _, sample) in NW_HEADS[context].items():
        mine = entry(models[NW_ID], context, head)["parts"]
        theirs = generated_entry(models, NW_GEN, counterpart)["parts"]
        assert fullmatch(mine, sample) and fullmatch(theirs, sample), head
        for text in near_misses:
            assert fullmatch(mine, text) is fullmatch(theirs, text) is False, (head, text)


@pytest.mark.parametrize("context", list(NW_HEADS))
def test_no_earlier_command_takes_a_nwdiag_head_line(models: ResolvedModels, context: str) -> None:
    """A head runs before the whole list, so no upstream-earlier rule may match it."""
    order = generated(models, NW_GEN)
    for head, (counterpart, _, _, sample) in NW_HEADS[context].items():
        earlier = order[: commands(order).index(counterpart)]
        hits = [e["command"] for e in earlier if fullmatch(e["parts"], sample)]
        assert hits == [], (head, hits)


def test_packet_main_is_heads_then_the_generated_order(models: ResolvedModels) -> None:
    got = commands(models[PK_ID].contexts[MAIN])
    assert got[: len(PK_HEADS)] == PK_HEADS
    body = commands(models[PK_ID].contexts[BODY])
    assert got[len(PK_HEADS) :] == body
    wanted = commands(generated(models, PK_GEN))
    assert [c for c in body if c in set(wanted)] == wanted
    assert body[body.index("CommandScaleInterval") + 1] == "CommandScaleIntervalError"


def test_packet_heads_carry_the_final_check(models: ResolvedModels) -> None:
    first, row, only = (entry(models[PK_ID], MAIN, h) for h in PK_HEADS)
    assert (first["push"], first["require_pop"]) == (BODY, True)
    assert (row["kind"], row["join"]["max_lines"], row["set"]) == ("multiline", 100000, BODY)
    assert (only["kind"], only["reject"]) == ("single", True)
    for context in (MAIN, BODY):
        assert entry(models[PK_ID], context, "CommandNumRange")["set"] == BODY


def test_packet_first_field_matches_what_num_range_matches(models: ResolvedModels) -> None:
    mine = entry(models[PK_ID], MAIN, "PacketFirstField")["parts"]
    theirs = generated_entry(models, PK_GEN, "CommandNumRange")["parts"]
    for text in PK_FIELD_SAMPLES + ["12345678: x", "1:x", "* ", "4-3:", "a-b: c"]:
        assert fullmatch(mine, text) is fullmatch(theirs, text), text


def test_no_earlier_command_takes_a_packet_field(models: ResolvedModels) -> None:
    order = generated(models, PK_GEN)
    earlier = order[: commands(order).index("CommandNumRange")]
    for text in PK_FIELD_SAMPLES:
        assert [e["command"] for e in earlier if fullmatch(e["parts"], text)] == [], text


def test_every_patch_key_matches_a_family_rule(
    raw_models: dict[str, Model], models: ResolvedModels
) -> None:
    for mid, gen_id, first in ((NW_ID, NW_GEN, NW_FIRST), (PK_ID, PK_GEN, PK_FIRST)):
        raw = raw_models[mid]
        keys = set(raw.overrides) | set(raw.insert_before) | set(raw.insert_after)
        assert keys and keys <= set(family_commands(models, gen_id, first)), mid


def hand_written(raw_models: dict[str, Model]) -> list[dict[str, Any]]:
    out = [e for mid in (NW_ID, PK_ID) for es in raw_models[mid].contexts.values() for e in es]
    out += [e for es in raw_models[PK_ID].insert_after.values() for e in es]
    return [e for e in out if "command" in e]


def test_hand_written_entries_cite_upstream_file_and_line(raw_models: dict[str, Model]) -> None:
    entries = hand_written(raw_models)
    assert len(entries) == 12
    for e in entries:
        prov = e["provenance"]
        assert prov["file"].startswith(UPSTREAM_PREFIX), e["command"]
        assert prov["line"] >= 1, e["command"]
        assert all(a.startswith(UPSTREAM_PREFIX) for a in prov.get("also", [])), e["command"]


def test_context_entries_do_not_cite_a_patched_class(raw_models: dict[str, Model]) -> None:
    for mid in (NW_ID, PK_ID):
        keys = set(raw_models[mid].overrides)
        for es in raw_models[mid].contexts.values():
            for e in (e for e in es if "command" in e):
                assert e["provenance"]["class"].rsplit(".", 1)[-1] not in keys, e["command"]


# --- zero-width fields: the patterns against an arithmetic reference -------------------

FIELD = re.compile(
    r"[ \t]*(?:(?P<u>[0-9]{1,7}):?|(?P<a>[0-9]{1,7})-(?P<b>[0-9]{1,7}):?|\*)[ \t]+"
    r"(?:.*?)(?:[ \t]*\[(?P<attr>.*?)\])?[ \t]*"
)
TO_SET = re.compile(r'\s*(\w+)\s*=\s*("([^"]*)"|[^\s,]+)', re.ASCII)
JAVA_INT = re.compile(r"[+-]?[0-9]+")


def java_len(attr: str | None) -> int:
    """CommandNumRange.getLengthAttribute over NwDiagram.toSet (last `len` wins)."""
    length = 1
    for found in TO_SET.finditer(attr or ""):
        if found[1] == "len":
            value = found[3] if found[3] is not None else found[2]
            ok = JAVA_INT.fullmatch(value) and abs(int(value)) <= JAVA_INT_MAX
            length = int(value) if ok else 1
    return length


def width(line: str) -> int | None:
    """Width of a field line per CommandNumRange.executeArg, or None if not a field."""
    found = FIELD.fullmatch(line)
    if found is None:
        return None
    if found["a"] is not None:
        return int(found["b"]) - int(found["a"]) + 1
    return java_len(found["attr"])


def range_lines() -> list[str]:
    lines = [f"{a}-{b}: x" for a in range(1201) for b in (a - 2, a - 1, a, a + 1) if b >= 0]
    lines += [f"0{a}-00{a - 1} d [len=1]" for a in range(1, 1201)]
    rng = random.Random(27)
    for _ in range(5000):
        a = rng.randint(1, 9_999_999)
        lines.append(f"{a}-{a - 1 if rng.random() < 0.5 else rng.randint(0, 9_999_999)} f")
    return lines


ATTRS = [
    "len=0", "len = 0", 'len="0"', "len=+0", "len=-0", "len=00", "len=1", "len=0, len=1",
    "len=1, len=0", "xlen=0", "a len=0", "foo, len=0", 'a="len=0"', "a=len=0", "len=0]",
    "len=0 height=2", " len = 0 , rotate = 90 ", "len=0x", 'len="0 "', "len=0 len",
    "len=0, b=x\x0blen=1", "height=2,len=0", 'len=0,a="b"', "len=-1", "len=0 len=",
]  # fmt: skip


def attribute_lines() -> list[str]:
    heads = ("*", "1", "12:", "7 :")
    lines = [f"{h} {d}[{a}]" for h in heads for d in ("A ", "", "A[b] ") for a in ATTRS]
    return lines + ["* A", "1 A", "* A [len=0] x", "1 A [len=0] [len=1]", "4-3:", "a-b x"]


@pytest.fixture(scope="module")
def zero_patterns(models: ResolvedModels) -> tuple[Any, Any]:
    variables = models[PK_ID].variables
    return compile_part(variables["PK_ZERO_FIELD"]), compile_part(variables["PK_NONZERO_FIELD"])


@pytest.mark.parametrize("lines", [range_lines, attribute_lines], ids=["range", "attribute"])
def test_zero_width_patterns_are_sound(zero_patterns: tuple[Any, Any], lines: Any) -> None:
    """Zero is detected only for width 0; every other field is a non-zero field."""
    zero, nonzero = zero_patterns
    for line in lines():
        w = width(line)
        is_zero = zero.fullmatch(line) is not None
        assert not is_zero or w == 0, line
        assert (nonzero.fullmatch(line) is not None) is (w is not None and not is_zero), line


def test_every_range_and_clean_attribute_zero_is_detected(zero_patterns: tuple[Any, Any]) -> None:
    zero, _ = zero_patterns
    clean = [line for line in range_lines() if width(line) == 0]
    # Known misses: other whitespace inside the bracket and a dangling `name=`.
    clean += [f"* A [{a}]" for a in ATTRS if "\x0b" not in a and not a.endswith("=")]
    missed = [line for line in clean if width(line) == 0 and zero.fullmatch(line) is None]
    assert missed == []


# --- interpreter behavior -------------------------------------------------------------


def verdict(models: ResolvedModels, keyword: str, body: list[str]) -> Any:
    return accepts(models, "\n".join([f"@start{keyword}", *body, f"@end{keyword}"]))


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (["4-3: x"], False),
        (["4-3: x", "title t", "0-15: y"], True),
        (["0-15: y", "4-3: x"], True),
        (["4-3: x", "0-15: y", "4-3: z"], True),
        (["* A [len=0]", "skinparam monochrome true", "* B [len=0]"], False),
        (["packetdiag {", "}"], True),
        (["scale_interval = 2147483648", "0-1: a"], False),
        (["scale_interval = 0002147483647", "0-1: a"], True),
    ],
)
def test_packet_verdicts(models: ResolvedModels, body: list[str], expected: bool) -> None:
    got = verdict(models, "packetdiag", body)
    assert got["accepted"] is expected
    assert got["model"] == (PK_ID if expected else None)


def test_zero_width_retry_validates_the_skipped_lines(models: ResolvedModels) -> None:
    got = verdict(models, "packetdiag", ["4-3: x", "colwidth = 1000", "0-15: y"])
    assert (got["accepted"], got["first_failure"]["line"]) == (False, 3)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (["network n {", "group {", "}", "description = x", "}", "}"], True),
        (["network n {", "}", "description = x"], False),
        (["group {", "a", "}", "group {", "b", "}"], True),
        (["network n {", "group {", "network m {"], False),
    ],
)
def test_nwdiag_verdicts(models: ResolvedModels, body: list[str], expected: bool) -> None:
    assert verdict(models, "nwdiag", body)["accepted"] is expected


# --- fixtures -------------------------------------------------------------------------


def fixtures(group: str) -> list[Path]:
    return sorted((FIXTURES / group).glob("*.puml"))


def header(path: Path) -> dict[str, str]:
    found = (HEADER.match(line) for line in path.read_text(encoding="utf-8").splitlines())
    return {m["key"]: m["value"] for m in found if m}


def fixture_commands(path: Path) -> list[str]:
    return [c.strip() for c in header(path)["nwdiag-packet"].split(",")]


def rel(path: Path) -> str:
    return path.relative_to(FIXTURES).as_posix()


def run(models: ResolvedModels, path: Path) -> Any:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    return accepts(models, block, raw=True)


@pytest.mark.parametrize("path", fixtures(POS), ids=rel)
def test_pos_fixture_is_accepted(models: ResolvedModels, path: Path) -> None:
    got = run(models, path)
    assert got["accepted"], got["first_failure"]
    assert got["model"] in (NW_ID, PK_ID)


@pytest.mark.parametrize("path", fixtures(NEG), ids=rel)
def test_neg_fixture_is_rejected(models: ResolvedModels, path: Path) -> None:
    assert run(models, path)["accepted"] is False


def gap_params() -> list[Any]:
    return [
        pytest.param(p, id=rel(p), marks=pytest.mark.xfail(strict=True, reason=header(p)["gap"]))
        for p in fixtures(GAP)
    ]


@pytest.mark.parametrize("path", gap_params())
def test_gap_fixture_is_rejected(models: ResolvedModels, path: Path) -> None:
    assert run(models, path)["accepted"] is False


def known_rules(raw_models: dict[str, Model], models: ResolvedModels) -> set[str]:
    rules = set(family_commands(models, NW_GEN, NW_FIRST))
    rules |= set(family_commands(models, PK_GEN, PK_FIRST))
    return rules | {e["command"] for e in hand_written(raw_models)}


def test_every_fixture_names_known_rules(
    raw_models: dict[str, Model], models: ResolvedModels
) -> None:
    known = known_rules(raw_models, models)
    for path in fixtures(POS) + fixtures(NEG) + fixtures(GAP):
        assert set(fixture_commands(path)) <= known, rel(path)


@pytest.mark.parametrize("group", [POS, NEG])
def test_every_generated_family_command_has_a_fixture(models: ResolvedModels, group: str) -> None:
    covered = {c for path in fixtures(group) for c in fixture_commands(path)}
    wanted = set(family_commands(models, NW_GEN, NW_FIRST))
    wanted |= set(family_commands(models, PK_GEN, PK_FIRST))
    if group == POS:
        wanted -= set(NW_REMOVED)
    assert wanted - covered == set()


def test_every_hand_written_rule_has_a_fixture(raw_models: dict[str, Model]) -> None:
    covered = {c for p in fixtures(POS) + fixtures(NEG) for c in fixture_commands(p)}
    assert {e["command"] for e in hand_written(raw_models)} - covered == set()


@pytest.mark.corpus
def test_fixture_verdicts_equal_the_oracle() -> None:
    from tools.validate.oracle import oracle_verdicts

    paths = fixtures(POS) + fixtures(NEG) + fixtures(GAP)
    verdicts = oracle_verdicts(paths)
    for path in paths:
        (block,) = verdicts[str(path)]
        assert block["accepted"] is (path.parent.name == POS), rel(path)
        if block["accepted"]:
            assert block["diagram_type"] in (NW_DIAGRAM, PK_DIAGRAM), rel(path)
