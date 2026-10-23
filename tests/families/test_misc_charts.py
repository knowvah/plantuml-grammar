"""Chart, Chen EER, wire, BPM and flow diagrams (T30, ``model/diagrams/misc-charts-*.yaml``).

One diagram model per factory (``misc-charts-{chart,chen,wire,bpm,flow}``), each the top
model of its factory, plus shared parts: ``misc-charts-colors`` (color words that resolve),
``misc-charts-chart-values`` (chart number grammars and line shapes) and
``misc-charts-wire-parts`` (wire shapes and indentation levels).

Fixtures (``tests/fixtures/misc-charts``), each with a header before ``@start``::

    ' misc-charts: RuleA, RuleB          rule ids the fixture exercises
    ' gap: <reason>                       gap/ only: why the model cannot reject it

``pos/`` is accepted by the jar, ``neg/`` and ``gap/`` are rejected by the jar (``corpus``
tests). Each start keyword has one factory, so the interpreter runs with full dispatch.
"""

from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Any

import pytest
import regex

from tools.interp import accepts
from tools.interp.compile import compile_part
from tools.interp.source import split_blocks
from tools.model import Model, ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve, top_models
from tools.report.coverage import (
    EXCLUDED,
    MODELED,
    build_matrix,
    load_exclusions,
    load_extracted,
)

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO / "model"
FIXTURES = REPO / "tests" / "fixtures" / "misc-charts"
POS, NEG, GAP = "pos", "neg", "gap"
HEADER = re.compile(r"^' (?P<key>misc-charts|gap): (?P<value>.+)$")
UPSTREAM_PREFIX = "src/main/java/net/sourceforge/plantuml/"
MAIN = "main"
COMMON_ID = "common"
# kind -> (model id, generated model id, factory, diagram, includes common)
FAMILY = {
    "chart": ("misc-charts-chart", "gen-chart-diagram", "ChartDiagramFactory", "CHART", True),
    "chen": ("misc-charts-chen", "gen-chen-eer-diagram", "ChenEerDiagramFactory", "CHEN_EER", True),
    "wire": ("misc-charts-wire", "gen-wire-diagram", "WireDiagramFactory", "WIRE", True),
    "bpm": ("misc-charts-bpm", "gen-bpm-diagram", "BpmDiagramFactory", "BPM", False),
    "flow": ("misc-charts-flow", "gen-flow-diagram", "FlowDiagramFactory", "FLOW", False),
}
SHARED = ("misc-charts-colors", "misc-charts-chart-values", "misc-charts-wire-parts")
CHEN_REMOVED = ("CommandCreateAttribute", "CommandEndGroup")
STATEFUL = ("misc-charts-chart", "misc-charts-wire")
WIRE_MAX_TRACKED = 4


@pytest.fixture(scope="module")
def raw_models() -> dict[str, Model]:
    return load_dir(MODEL_DIR)


@pytest.fixture(scope="module")
def models(raw_models: dict[str, Model]) -> ResolvedModels:
    return resolve(raw_models)


def commands(entries: list[dict[str, Any]]) -> list[str]:
    return [e["command"] for e in entries if "command" in e]


def variable(models: ResolvedModels, model_id: str, name: str) -> Any:
    return compile_part(models[model_id].variables[name])


def hand_written(raw_models: dict[str, Model]) -> list[tuple[str, dict[str, Any]]]:
    """Every entry written in the family models: contexts and inserts."""
    found = []
    for model_id in [f[0] for f in FAMILY.values()]:
        raw = raw_models[model_id]
        for entries in raw.contexts.values():
            found += [(model_id, e) for e in entries if "command" in e]
        for key in ("insert_before", "insert_after"):
            doc = getattr(raw, key, None) or {}
            found += [(model_id, e) for entries in doc.values() for e in entries]
    return found


# --- model shape -----------------------------------------------------------------------


@pytest.mark.parametrize("kind", sorted(FAMILY))
def test_family_model_is_the_top_model_of_its_factory(
    raw_models: dict[str, Model], models: ResolvedModels, kind: str
) -> None:
    model_id, generated, factory, diagram, with_common = FAMILY[kind]
    raw = raw_models[model_id]
    assert (raw.layer, raw.diagram, raw.factory) == ("diagram", diagram, factory)
    assert raw.include[0] == generated
    assert (COMMON_ID in raw.include) is with_common
    assert top_models(models)[factory] == model_id


def test_shared_parts_are_shared_models(raw_models: dict[str, Model]) -> None:
    assert [raw_models[m].layer for m in SHARED] == ["shared"] * len(SHARED)
    assert all(raw_models[m].diagram is None for m in SHARED)


@pytest.mark.parametrize("kind", sorted(FAMILY))
def test_main_keeps_the_generated_order(models: ResolvedModels, kind: str) -> None:
    model_id, generated = FAMILY[kind][:2]
    wanted = [c for c in commands(models[generated].contexts[MAIN]) if c not in CHEN_REMOVED]
    got = commands(models[model_id].contexts[MAIN])
    assert [c for c in got if c in set(wanted)] == wanted


def test_chen_removes_the_owner_commands_and_excludes_them(models: ResolvedModels) -> None:
    chen = models["misc-charts-chen"]
    found = {c for entries in chen.contexts.values() for c in commands(entries)}
    assert not found & set(CHEN_REMOVED)
    excluded = load_exclusions()
    assert all(f"net.sourceforge.plantuml.cheneer.command.{c}" in excluded for c in CHEN_REMOVED)


@pytest.mark.parametrize("kind", sorted(FAMILY))
def test_every_extracted_command_is_modeled_or_excluded(models: ResolvedModels, kind: str) -> None:
    factory = FAMILY[kind][2]
    extracted = {factory: load_extracted()[factory]}
    matrix = build_matrix(extracted, models, load_exclusions())
    assert {
        c.simple: c.status for c in matrix[factory] if c.status not in (MODELED, EXCLUDED)
    } == {}


def test_bpm_branch_heads_keep_else_and_pop_on_end(models: ResolvedModels) -> None:
    bpm = models["misc-charts-bpm"]
    head = bpm.contexts["bpm_branch"][:2]
    assert [(e["command"], e.get("pop")) for e in head] == [
        ("BpmBranchElse", None),
        ("BpmBranchEnd", True),
    ]
    main = {e["command"]: e for e in bpm.contexts[MAIN]}
    assert main["CommandNewBranch"]["push"] == "bpm_branch"
    assert main["CommandElseBranch"]["reject"] and main["CommandEndBranch"]["reject"]


def test_flow_link_needs_a_box(models: ResolvedModels) -> None:
    flow = models["misc-charts-flow"]
    main = {e["command"]: e for e in flow.contexts[MAIN]}
    assert main["CommandLink"]["reject"] is True
    assert main["CommandLineSimple"]["set"] == "flow_boxes"
    assert flow.contexts["flow_boxes"][0]["command"] == "FlowLinkToBox"


def test_state_heads_are_interpreter_only_and_untrimmed(
    raw_models: dict[str, Model],
) -> None:
    for model_id, entry in hand_written(raw_models):
        if model_id not in STATEFUL:
            continue
        assert entry.get("trim") is False, entry["command"]
        if "set" in entry:
            assert entry.get("emit") is False, entry["command"]


CHEN_CHECKED = {
    "Entity": "CommandCreateEntity",
    "Associate": "CommandAssociate",
    "SimpleSubclass": "CommandSimpleSubclass",
    "MultiSubclass": "CommandMultiSubclass",
}


@pytest.mark.parametrize("rule", sorted(CHEN_CHECKED))
def test_each_chen_reject_follows_its_checked_copy(models: ResolvedModels, rule: str) -> None:
    got = commands(models["misc-charts-chen"].contexts[MAIN])
    i = got.index(f"Chen{rule}Checked")
    assert got[i + 1 : i + 3] == [f"Chen{rule}Fails", CHEN_CHECKED[rule]]


@pytest.mark.parametrize("model_id", STATEFUL)
def test_each_narrowed_rule_is_followed_by_its_reject(
    raw_models: dict[str, Model], models: ResolvedModels, model_id: str
) -> None:
    got = commands(models[model_id].contexts[MAIN])
    for key, inserts in raw_models[model_id].insert_after.items():
        (reject,) = inserts
        assert reject["reject"] is True
        assert got[got.index(key) + 1] == reject["command"]


def test_hand_written_entries_cite_an_upstream_file_and_line(
    raw_models: dict[str, Model],
) -> None:
    for _, entry in hand_written(raw_models):
        prov = entry["provenance"]
        assert prov["file"].startswith(UPSTREAM_PREFIX), entry["command"]
        assert isinstance(prov["line"], int), entry["command"]


# --- colors ----------------------------------------------------------------------------

HASH_COLORS = [
    ("#red", True),
    ("#F", True),
    ("#ff", False),
    ("#fff", True),
    ("#ffff", False),
    ("#ff0000", True),
    ("#ff0000aa", True),
    ("#automatic", True),
    ("#Transparent", True),
    ("#zzzz", False),
    ("#red_", False),
]
COLOR_SPECS = [
    ("#back:red;line:blue", True),
    ("#back", False),
    ("#red;back", False),
    ("#red;line.bold", True),
    ("#red-blue", True),
    ("#red-bluex", False),
    ("#ff-red", False),
    ("#f-red", True),
    ("#transparent-red", False),
    ("#shadowing:xx", True),
    ("#text:anything", True),
    ("", True),
]


@pytest.mark.parametrize(("text", "ok"), HASH_COLORS)
def test_hash_color_words(models: ResolvedModels, text: str, ok: bool) -> None:
    rx = variable(models, "misc-charts-colors", "MC_HASH_COLOR_OK")
    assert (rx.fullmatch(text) is not None) is ok


@pytest.mark.parametrize(("text", "ok"), COLOR_SPECS)
def test_colors_specs(models: ResolvedModels, text: str, ok: bool) -> None:
    rx = variable(models, "misc-charts-colors", "MC_COLORS_OK")
    assert (rx.fullmatch(text) is not None) is ok


# --- chart number grammars: generator, Java reference, fuzz ----------------------------

TRIM = r"[\x00-\x09\x0B\x0C\x0E-\x20]"
BLANK = r"[ \t\x0B\f]"
GAP_RX = f"{BLANK}*"
DOUBLE = (
    r"[+-]?(?:0[xX](?:[0-9a-fA-F]+(?:\.[0-9a-fA-F]*)?|\.[0-9a-fA-F]+)[pP][+-]?[0-9]+[fFdD]?"
    r"|NaN|Infinity|(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?[fFdD]?)"
)
JAVA_DOUBLE = re.compile(DOUBLE)


def interleave(rx: str, gap: str) -> str:
    """Allow ``gap`` after every character atom of a restricted regex."""
    out, i = [], 0
    while i < len(rx):
        if rx[i] == "[":
            j = i + 1
            while rx[j] != "]":
                j += 2 if rx[j] == "\\" else 1
            out.append(f"(?:{rx[i : j + 1]}{gap})")
            i = j + 1
        elif rx[i] == "\\":
            out.append(f"(?:{rx[i : i + 2]}{gap})")
            i += 2
        elif rx.startswith("(?:", i):
            out.append("(?:")
            i += 3
        elif rx[i] in "()|?*+":
            out.append(rx[i])
            i += 1
        else:
            out.append(f"(?:{re.escape(rx[i])}{gap})")
            i += 1
    return "".join(out)


def generated_number_regexes() -> dict[str, str]:
    item = rf"{TRIM}*{DOUBLE}{TRIM}*"
    tick_rest = rf'{DOUBLE}{TRIM}*:{TRIM}*"[^,]*"{TRIM}*'
    pair = interleave(rf"[\[(]*{DOUBLE},{DOUBLE},*", GAP_RX)
    pair += rf"(?:\]{GAP_RX}|\)(?!{GAP_RX},{GAP_RX}\(){GAP_RX})*"
    sep = interleave(r"\),\(", GAP_RX)
    return {
        "CH_DOUBLE": DOUBLE,
        "CH_VALUES": rf"(?:,+|{TRIM}*(?:{DOUBLE}{TRIM}*(?:,{item})*,*)?)",
        "CH_TICKS": rf"(?:,+|{TRIM}*(?:{tick_rest}(?:,{TRIM}*{tick_rest})*,*)?)",
        "CH_PAIRS": f"{GAP_RX}(?:{pair}(?:{sep}{pair})*)?(?:{sep})*",
        "CH_YPOS": DOUBLE + TRIM + r"*(?=\))",
    }


def jtrim(s: str) -> str:
    a, b = 0, len(s)
    while a < b and s[a] <= " ":
        a += 1
    while b > a and s[b - 1] <= " ":
        b -= 1
    return s[a:b]


def jsplit(s: str, sep: str) -> list[str]:
    """``String.split``: no match gives ``[s]``; trailing empty strings are dropped."""
    if not re.search(sep, s):
        return [s]
    parts = re.split(sep, s)
    while parts and parts[-1] == "":
        parts.pop()
    return parts


def jdouble(s: str) -> bool:
    return JAVA_DOUBLE.fullmatch(jtrim(s)) is not None


def ref_values(data: str) -> bool:
    return jtrim(data) == "" or all(jdouble(p) for p in jsplit(data, ","))


def ref_pair(pair: str) -> bool:
    p = re.sub(r"[\])]+$", "", re.sub(r"^[\[(]+", "", jtrim(pair)))
    coords = jsplit(p, ",")
    return len(coords) == 2 and jdouble(coords[0]) and jdouble(coords[1])


def ref_pairs(data: str) -> bool:
    cleaned = re.sub(r"[ \t\n\x0B\f\r]+", "", data)
    return jtrim(data) != "" and all(ref_pair(p) for p in jsplit(cleaned, r"\),\("))


def ref_tick(pair: str) -> bool:
    pair = jtrim(pair)
    colon = pair.find(":")
    label = jtrim(pair[colon + 1 :])
    quoted = label.startswith('"') and label.endswith('"') and len(label) > 1
    return colon >= 0 and quoted and jdouble(pair[:colon])


def ref_ticks(data: str) -> bool:
    return jtrim(data) == "" or all(ref_tick(p) for p in jsplit(data, ","))


ALPHABET = [*'0123456789.,()[]-+eExXpPfFdD :"aN', "NaN", "Infinity", "0x1", "1.5", "),(", "\t"]
REFERENCES = {"CH_VALUES": ref_values, "CH_PAIRS": ref_pairs, "CH_TICKS": ref_ticks}
FUZZ_ROUNDS = 20000


def fuzz_strings(seed: int, count: int) -> list[str]:
    rnd = random.Random(seed)
    return ["".join(rnd.choice(ALPHABET) for _ in range(rnd.randint(0, 12))) for _ in range(count)]


@pytest.mark.parametrize("name", sorted(generated_number_regexes()))
def test_chart_number_regexes_match_their_generator(
    raw_models: dict[str, Model], name: str
) -> None:
    raw = raw_models["misc-charts-chart-values"].variables[name]
    assert raw["regex"] == generated_number_regexes()[name]


@pytest.mark.parametrize("name", sorted(REFERENCES))
def test_chart_number_grammar_agrees_with_the_java_reference(name: str) -> None:
    rx = regex.compile(generated_number_regexes()[name])
    ref = REFERENCES[name]
    for text in fuzz_strings(sum(map(ord, name)), FUZZ_ROUNDS):
        if name == "CH_PAIRS" and "(" not in text:
            continue
        assert (rx.fullmatch(text) is not None) is ref(text), repr(text)


@pytest.mark.parametrize("name", sorted(REFERENCES))
def test_chart_number_first_match_covers_valid_data(name: str) -> None:
    """The first match (``regex.match``) spans the whole valid datum: no undershoot."""
    rx = regex.compile(generated_number_regexes()[name])
    for text in fuzz_strings(17, FUZZ_ROUNDS):
        if REFERENCES[name](text) and (name != "CH_PAIRS" or "(" in text):
            found = rx.match(text + "] #red")
            assert found is not None and found.end() >= len(text), repr(text)


# Double.parseDouble verdicts, checked against the jar in the corpus test.
JAVA_DOUBLES = [
    ("+NaN", True),
    ("-Infinity", True),
    ("Infinityf", False),
    ("NaNd", False),
    ("1e5d", True),
    ("0x1p-3D", True),
    ("1_000", False),
    ("1e", False),
    ("0x1.", False),
    ("0x1.p1", True),
    (".", False),
    ("-.5e1", True),
    ("0X1P1F", True),
    ("infinity", False),
    ("1.e2", True),
    ("5L", False),
    ("1d5", False),
    ("0x1.8p+1d", True),
    ("١", False),
]


@pytest.mark.parametrize(("text", "ok"), JAVA_DOUBLES)
def test_chart_double_literal(text: str, ok: bool) -> None:
    assert (JAVA_DOUBLE.fullmatch(text) is not None) is ok


# --- wire indentation levels -----------------------------------------------------------


def java_level(indent: str) -> int:
    """WireDiagram.computeIndentationLevel (WireDiagram.java:137-140)."""
    return len(indent.replace("    ", "\t"))


def indents(seed: int) -> list[str]:
    rnd = random.Random(seed)
    return [
        "".join(rnd.choice(" \t\x0b\f") for _ in range(rnd.randint(0, 14))) for _ in range(3000)
    ]


@pytest.mark.parametrize("level", range(WIRE_MAX_TRACKED + 1))
def test_wire_level_lookaheads_follow_java(models: ResolvedModels, level: int) -> None:
    exact = variable(models, "misc-charts-wire-parts", f"WI_LEVEL_IS_{level}")
    over = variable(models, "misc-charts-wire-parts", f"WI_LEVEL_OVER_{level}")
    for indent in indents(level):
        line = indent + "* a"
        assert (exact.match(line) is not None) is (java_level(indent) == level), repr(indent)
        assert (over.match(line) is not None) is (java_level(indent) > level), repr(indent)


# --- fixtures --------------------------------------------------------------------------


def fixtures(group: str) -> list[Path]:
    return sorted((FIXTURES / group).glob("*.puml"))


def rel(path: Path) -> str:
    return f"{path.parent.name}/{path.stem}"


def header(path: Path) -> dict[str, str]:
    found = (HEADER.match(line) for line in path.read_text(encoding="utf-8").splitlines())
    return {m["key"]: m["value"] for m in found if m}


def named_rules(path: Path) -> set[str]:
    return {c.strip() for c in header(path)["misc-charts"].split(",")}


def kind_of(path: Path) -> str:
    return path.stem.split("-")[0]


def verdict(models: ResolvedModels, path: Path) -> Any:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    return accepts(models, block, raw=True)


@pytest.mark.parametrize("path", fixtures(POS), ids=rel)
def test_pos_fixture_is_accepted(models: ResolvedModels, path: Path) -> None:
    got = verdict(models, path)
    assert got["accepted"] is True, got
    assert got["diagram"] == FAMILY[kind_of(path)][3]


@pytest.mark.parametrize("path", fixtures(NEG), ids=rel)
def test_neg_fixture_is_rejected(models: ResolvedModels, path: Path) -> None:
    assert verdict(models, path)["accepted"] is False


def gap_params() -> list[Any]:
    marks = []
    for path in fixtures(GAP):
        reason = header(path)["gap"]
        marks.append(
            pytest.param(path, id=rel(path), marks=pytest.mark.xfail(reason=reason, strict=True))
        )
    return marks


@pytest.mark.parametrize("path", gap_params())
def test_gap_fixture_is_rejected(models: ResolvedModels, path: Path) -> None:
    assert verdict(models, path)["accepted"] is False


def all_rule_ids(models: ResolvedModels) -> set[str]:
    return {
        c
        for model_id in [f[0] for f in FAMILY.values()]
        for entries in models[model_id].contexts.values()
        for c in commands(entries)
    }


def test_every_fixture_names_rules_of_the_family(models: ResolvedModels) -> None:
    known = all_rule_ids(models)
    for path in fixtures(POS) + fixtures(NEG) + fixtures(GAP):
        assert named_rules(path) <= known, (rel(path), named_rules(path) - known)


def test_every_hand_written_rule_has_a_fixture(raw_models: dict[str, Model]) -> None:
    named = set().union(*(named_rules(p) for p in fixtures(POS) + fixtures(NEG) + fixtures(GAP)))
    written = {e["command"] for _, e in hand_written(raw_models)}
    assert written - named == set()


def family_rejects(raw_models: dict[str, Model]) -> set[str]:
    """Rejects declared by the family models: hand-written entries and overrides."""
    written = {e["command"] for _, e in hand_written(raw_models) if e.get("reject")}
    overridden = {
        key
        for model_id in [f[0] for f in FAMILY.values()]
        for key, patch in (raw_models[model_id].overrides or {}).items()
        if patch.get("reject")
    }
    return written | overridden


def test_every_reject_has_a_neg_fixture(raw_models: dict[str, Model]) -> None:
    named = set().union(*(named_rules(p) for p in fixtures(NEG)))
    assert family_rejects(raw_models) - named == set()


# --- inline cases (interpreter here, jar in the corpus test) ---------------------------

# (start keyword, body, accepted by the jar).
INLINE_CASES = [
    ("bpm", ":a;\nelse", False),
    ("bpm", "new branch\nelse\nelse\nend branch\nend branch", False),
    ("bpm", "ELSE", False),
    ("bpm", ":a;\ngoto nowhere", True),
    ("bpm", "resume nowhere", True),
    ("bpm", "NEW   BRANCH", True),
    ("flow", "20", False),
    ("flow", '10 "A"\n10 "B"', True),
    ("flow", '10 "A"\ns 20 "B"\nn 10', True),
    ("chen", "RELATIONSHIP A {\n}", False),
    ("chen", "}", False),
    ("chen", "a", False),
    ("chen", "entity A. {\n}", True),
    ("chen", "entity M #back {\n}", False),
    ("chen", "entity M #red;line.bold {\n}", True),
    ("chen", "entity M #fff-red {\n}", True),
    ("chen", "entity M #transparent-red {\n}", False),
    ("chen", "entity A {\nentity B {\n}\nx\n}", True),
    ("chen", "left to right direction", True),
    ("wire", "* a\n    * b", True),
    ("wire", "* a\n     * b", False),
    ("wire", "* a\n\t--", True),
    ("wire", "\tmove(1,2)", False),
    ("wire", "* a [2147483647x2147483647]", True),
    ("wire", "* a #f", True),
    ("wire", "* a\n spot a", False),
    ("wire", "title x\n\t* a", False),
    ("wire", "* a\n\t\n* b", True),
    ("wire", "* a\n \t* b", False),
    ("wire", "* a\n\t* b\n        * c", True),
    ("chart", "bar [,1]", False),
    ("chart", "bar [0x10]", False),
    ("chart", "bar [1e]", False),
    ("chart", "BAR [1]", True),
    ("chart", "h-axis spacing 5", True),
    ("chart", "v-axis spacing .", False),
    ("chart", "v-axis spacing 0.5", True),
    ("chart", 'v-axis ticks [x:"a"]', False),
    ("chart", "v-axis ticks [0]", False),
    ("chart", 'v-axis ticks [0:"]', False),
    ("chart", 'v-axis ticks [0:"a":"b"]', True),
    ("chart", "v-axis [a] ticks [x]", True),
    ("chart", "v-axis ticks [x] [a]", False),
    ("chart", "bar <<(C,#zzzz) x>> [1]", True),
    ("chart", 'annotation "x" at (a, NaN)', True),
    ("chart", 'h-axis "x" 0 --> 5\nbar [(1,2)]', False),
    ("chart", "h-axis 0 --> 5\nh-axis\nline [(1,2)]", True),
    ("chart", "h-axis 0 --> 5\nline [(1,2)]\nscatter [(2,3)]", True),
    ("chart", "legend LEFT\nstackmode STACKED\norientation Horizontal", True),
]


def body_verdict(models: ResolvedModels, kind: str, body: str) -> bool:
    return bool(accepts(models, f"@start{kind}\n{body}\n@end{kind}\n")["accepted"])


@pytest.mark.parametrize(("kind", "body", "accepted"), INLINE_CASES)
def test_inline_case(models: ResolvedModels, kind: str, body: str, accepted: bool) -> None:
    assert body_verdict(models, kind, body) is accepted


# --- corpus: oracle verdicts -----------------------------------------------------------


def oracle(paths: list[Path]) -> dict[str, Any]:
    from tools.validate.oracle import oracle_verdicts

    return oracle_verdicts(paths)


def write_blocks(tmp_path: Path, blocks: list[tuple[str, str]]) -> list[Path]:
    paths = []
    for index, (kind, body) in enumerate(blocks):
        path = tmp_path / f"case{index}.puml"
        path.write_text(f"@start{kind}\n{body}\n@end{kind}\n", encoding="utf-8")
        paths.append(path)
    return paths


@pytest.mark.corpus
def test_fixture_verdicts_equal_the_oracle() -> None:
    paths = fixtures(POS) + fixtures(NEG) + fixtures(GAP)
    verdicts = oracle(paths)
    for path in paths:
        (block,) = verdicts[str(path)]
        assert block["accepted"] is (path.parent.name == POS), rel(path)
        if path.parent.name == POS:
            assert block["diagram_type"] == FAMILY[kind_of(path)][3], rel(path)


@pytest.mark.corpus
def test_inline_cases_equal_the_oracle(tmp_path: Path) -> None:
    paths = write_blocks(tmp_path, [(k, b) for k, b, _ in INLINE_CASES])
    verdicts = oracle(paths)
    for path, (_, body, accepted) in zip(paths, INLINE_CASES, strict=True):
        assert verdicts[str(path)][0]["accepted"] is accepted, body


@pytest.mark.corpus
def test_double_literals_equal_the_oracle(tmp_path: Path) -> None:
    paths = write_blocks(tmp_path, [("chart", f"bar [{text}]") for text, _ in JAVA_DOUBLES])
    verdicts = oracle(paths)
    for path, (text, ok) in zip(paths, JAVA_DOUBLES, strict=True):
        assert verdicts[str(path)][0]["accepted"] is ok, text
