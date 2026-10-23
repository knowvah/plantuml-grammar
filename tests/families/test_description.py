"""Description diagrams (T19, ``model/diagrams/description.yaml``, ``id: description``).

``description`` is the top model of ``DescriptionDiagramFactory`` (usecase, component,
deployment, archimate). It includes the generated model, ``common`` and the class
family's ``class-objects`` (map and JSON bodies) and defines one context per group-stack
state, each running the whole generated command list after a few head entries (see the
model header).

Fixtures (``tests/fixtures/description``), one block each, with a header before
``@start``::

    ' description: RuleA, RuleB   rule ids the fixture exercises
    ' gap: <reason>               gap/ only: why the model cannot reproduce the jar

``pos/`` is accepted (as DESCRIPTION) and ``neg/`` and ``gap/`` rejected by the jar
(``corpus`` test). The interpreter runs each fixture raw with dispatch restricted to
DescriptionDiagramFactory; the neg fixtures use description-only syntax so that every
other factory rejects them too.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.emit.skip import skipped
from tools.interp import accepts
from tools.interp.compile import compile_part
from tools.interp.source import split_blocks
from tools.model import Model, ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve, top_models

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO / "model"
FIXTURES = REPO / "tests" / "fixtures" / "description"
POS, NEG, GAP = "pos", "neg", "gap"
DESC_ID = "description"
GEN_ID = "gen-description-diagram"
FACTORY = "DescriptionDiagramFactory"
DIAGRAM = "DESCRIPTION"
MAIN = "main"
TOGETHER, GROUP, ORPHAN = "desc_together", "desc_group", "desc_orphan"
STATE_CONTEXTS = (MAIN, TOGETHER, GROUP, ORPHAN)
START_MAP = {"uml": [FACTORY]}
UPSTREAM_PREFIX = "src/main/java/"
HEADER = re.compile(r"^' (?P<key>description|gap): (?P<value>.+)$")
COMMAND, PROVENANCE, PARTS = "command", "provenance", "parts"
CCEF = "CommandCreateElementFull"
ML0, ML1 = "CommandCreateElementMultilines_59", "CommandCreateElementMultilines_60"
DOMAIN = "CommandCreateDomain"
PORT_AT_ROOT, ORPHAN_REJECT = "PortAtRoot", "GroupStackEmpty"
REMOVED = frozenset({"CommandTogether", "CommandEndPackage"})
CLASSIFY = REPO / "reports" / "classify" / "description.yaml"
# Rejects owned by other families' shared models (their fixtures live there).
FOREIGN_REJECT_MODELS = ("common-errors", "class-objects", "style")


@cache
def raw_models() -> dict[str, Model]:
    return load_dir(MODEL_DIR)


@cache
def models() -> ResolvedModels:
    return resolve(raw_models())


def entries(context: str) -> list[dict[str, Any]]:
    return list(models()[DESC_ID].contexts[context])


def command_ids(context: str) -> list[str]:
    return [str(e[COMMAND]) for e in entries(context)]


def gen_entries() -> list[dict[str, Any]]:
    return list(models()[GEN_ID].contexts[MAIN])


def gen_entry(command: str) -> dict[str, Any]:
    return next(e for e in gen_entries() if e[COMMAND] == command)


def desc_entry(context: str, command: str) -> dict[str, Any]:
    return next(e for e in entries(context) if e[COMMAND] == command)


def raw_variable(name: str) -> Any:
    return raw_models()[DESC_ID].variables[name]


def resolved_variable(name: str) -> Any:
    return models()[DESC_ID].variables[name]


def fixtures(group: str) -> list[Path]:
    return sorted((FIXTURES / group).glob("*.puml"))


def rel(path: Path) -> str:
    return f"{path.parent.name}/{path.stem}"


def header(path: Path) -> dict[str, str]:
    found = (HEADER.match(line) for line in path.read_text(encoding="utf-8").splitlines())
    return {m["key"]: m["value"] for m in found if m}


def desc_verdict(path: Path) -> bool:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    return bool(accepts(models(), block, raw=True, start_map=START_MAP)["accepted"])


def body_verdict(body: str) -> bool:
    block = f"@startuml\n{body}\n@enduml\n"
    return bool(accepts(models(), block, start_map=START_MAP)["accepted"])


# --- model shape -----------------------------------------------------------------------


def test_description_is_the_top_model_of_the_description_factory() -> None:
    model = models()[DESC_ID]
    assert top_models(models())[FACTORY] == DESC_ID
    assert (model.layer, model.diagram, model.factory) == ("diagram", DIAGRAM, FACTORY)
    assert set(model.includes) >= {GEN_ID, "common", "class-objects"}


@pytest.mark.parametrize("context", STATE_CONTEXTS)
def test_every_state_runs_the_generated_list_in_upstream_order(context: str) -> None:
    generated = [str(e[COMMAND]) for e in gen_entries() if e[COMMAND] not in REMOVED]
    present = [c for c in command_ids(context) if c in set(generated)]
    assert present == generated


def test_state_dependent_generated_rules_are_replaced_by_head_entries() -> None:
    for context in STATE_CONTEXTS:
        assert REMOVED.isdisjoint(command_ids(context))
    exclusions = yaml.safe_load(CLASSIFY.read_text(encoding="utf-8"))["exclusions"]
    assert set(exclusions) == REMOVED


@pytest.mark.parametrize(
    ("context", "heads"),
    [
        (MAIN, [PORT_AT_ROOT, "RootTogether", "RootEnd"]),
        (TOGETHER, ["GroupEnd", PORT_AT_ROOT, "RootTogether"]),
        (GROUP, ["GroupEnd", "GroupTogether"]),
        (ORPHAN, [ORPHAN_REJECT]),
    ],
)
def test_head_entries_precede_the_generated_list(context: str, heads: list[str]) -> None:
    first = str(gen_entries()[0][COMMAND])
    ids = command_ids(context)
    assert ids[: ids.index(first)] == heads


@pytest.mark.parametrize(
    ("command", "key", "target"),
    [
        ("CommandPackageWithUSymbol", "push", GROUP),
        ("CommandArchimatePackage", "push", GROUP),
        ("CommandCreateDomainGroup", "push", GROUP),
        ("CommandNewpage", "set", MAIN),
    ],
)
def test_group_openers_and_newpage_act_alike_in_every_state(
    command: str, key: str, target: str
) -> None:
    for context in STATE_CONTEXTS:
        assert desc_entry(context, command)[key] == target


@pytest.mark.parametrize(
    ("context", "command", "key", "target"),
    [
        (MAIN, "RootTogether", "push", TOGETHER),
        (MAIN, "RootEnd", "set", ORPHAN),
        (TOGETHER, "RootTogether", "push", TOGETHER),
        (TOGETHER, "GroupEnd", "pop", True),
        (GROUP, "GroupTogether", "push", GROUP),
        (GROUP, "GroupEnd", "pop", True),
    ],
)
def test_together_and_close_depend_on_the_state(
    context: str, command: str, key: str, target: str | bool
) -> None:
    assert desc_entry(context, command)[key] == target


HEAD_SAMPLES = [
    "together {",
    "TOGETHER{",
    "together \u00a0 {",
    "together",
    "together { x",
    "}",
    "} ",
    "}}",
]


@pytest.mark.parametrize(
    ("context", "command", "generated"),
    [
        (MAIN, "RootTogether", "CommandTogether"),
        (GROUP, "GroupTogether", "CommandTogether"),
        (MAIN, "RootEnd", "CommandEndPackage"),
        (GROUP, "GroupEnd", "CommandEndPackage"),
    ],
)
def test_heads_match_what_the_removed_generated_rule_matched(
    context: str, command: str, generated: str
) -> None:
    head = compile_part(desc_entry(context, command)[PARTS])
    gen = compile_part(gen_entry(generated)[PARTS])
    for line in HEAD_SAMPLES:
        assert bool(head.fullmatch(line)) is bool(gen.fullmatch(line)), line


def test_rejects_sit_right_after_the_narrowed_rule() -> None:
    ids = command_ids(MAIN)
    for rule, after in [
        (CCEF, "CommandCreateElementFullForbidden"),
        (ML0, "CommandCreateElementMultilinesBadSymbol0"),
        (ML1, "CommandCreateElementMultilinesBadSymbol1"),
        (DOMAIN, "CommandCreateDomainGroup"),
    ]:
        assert ids.index(after) == ids.index(rule) + 1
        assert desc_entry(MAIN, rule)["refined_by"] == DESC_ID


def test_rejects_are_dropped_by_emitters_and_narrowed_rules_are_kept() -> None:
    for command in ("CommandCreateElementFullForbidden", PORT_AT_ROOT):
        assert skipped(desc_entry(MAIN, command)) is True
    assert skipped(desc_entry(MAIN, CCEF)) is False


# Generated shapes copied as variables, and where they come from in the generated rule.
COPIES = [
    ("D_ELEMENT_FULL", lambda: gen_entry(CCEF)[PARTS]),
    ("D_COLOR2", lambda: gen_entry(CCEF)[PARTS]["seq"][1]),
    ("D_ELEMENT_TAIL", lambda: {"seq": gen_entry(CCEF)[PARTS]["seq"][4:]}),
    ("D_ELEMENT_ML0_TAIL", lambda: {"seq": gen_entry(ML0)[PARTS]["seq"][1:]}),
    ("D_ELEMENT_ML1_TAIL", lambda: {"seq": gen_entry(ML1)[PARTS]["seq"][1:]}),
    ("D_DOMAIN_HEAD", lambda: {"seq": gen_entry(DOMAIN)[PARTS]["seq"][:-1]}),
]


@pytest.mark.parametrize(("name", "source"), COPIES, ids=[c[0] for c in COPIES])
def test_generated_shape_copies_equal_the_generated_rule(name: str, source: Any) -> None:
    assert resolved_variable(name) == source()


def test_the_domain_copy_drops_exactly_the_optional_group() -> None:
    assert gen_entry(DOMAIN)[PARTS]["seq"][-1]["regex"] == "(\\{)?"


def test_multiline_types_split_all_types_in_two() -> None:
    all_types = re.fullmatch(r"\((.+)\)\[.+\]\+", gen_entry(ML0)[PARTS]["seq"][0]["regex"])
    ok = re.fullmatch(r"\((.+)\)\[.+\]\+", raw_variable("D_ML_TYPE_OK")["regex"])
    bad = re.fullmatch(r"\((.+)\)\[.+\]\+", raw_variable("D_ML_TYPE_BAD")["regex"])
    assert all_types and ok and bad
    names = all_types[1].split("|")
    assert sorted(ok[1].split("|") + bad[1].split("|")) == sorted(names)
    assert bad[1].split("|") == ["actor/", "port", "portin", "portout"]


def matches(variable: str, line: str) -> bool:
    return bool(compile_part(resolved_variable(variable)).fullmatch(line))


@pytest.mark.parametrize(
    ("line", "forbidden"),
    [
        ("foo", True),
        ("licenses", True),
        ("été", True),
        ("A.b_c9", True),
        ("x١", False),
        ("foo bar", False),
        ("[A]", False),
        ("(A)", False),
    ],
)
def test_forbidden_is_one_bare_word_with_ascii_digits(line: str, forbidden: bool) -> None:
    assert matches("D_FORBIDDEN", line) is forbidden
    narrowed = compile_part(desc_entry(MAIN, CCEF)[PARTS])
    if forbidden:
        assert narrowed.fullmatch(line) is None


@pytest.mark.parametrize(
    ("line", "port"),
    [
        ("port t", True),
        ("portin t", True),
        ("portout t #red", True),
        ('port "t" as x', True),
        ('port x as "y"', True),
        ("port t <<s>>", True),
        ("port (t)", False),
        ("port [t]", False),
        ("port :t:", False),
        ("port ()t", False),
        ("port x as (y)", False),
        ("porta t", False),
    ],
)
def test_port_at_root_spares_short_forms(line: str, port: bool) -> None:
    assert matches("D_PORT_ROOT", line) is port


@pytest.mark.parametrize(
    ("line", "unsafe"),
    [
        ("[d]", True),
        ("c --> d", True),
        ("}", True),
        ("together {", True),
        ('note "x" as n', True),
        ("titles x", True),
        ("title x", False),
        ("left header x", False),
        ("left to right direction", False),
        ("hide c", False),
        ("url of c is [[http://x]]", False),
        ("<style>", False),
        ("!pragma layout smetana", False),
    ],
)
def test_orphan_reject_spares_the_commands_that_never_touch_the_stack(
    line: str, unsafe: bool
) -> None:
    assert matches("D_ORPHAN_UNSAFE", line) is unsafe


def hand_written() -> Iterator[dict[str, Any]]:
    gen = {str(e[COMMAND]) for e in gen_entries()}
    own = {str(e[COMMAND]) for es in raw_models()[DESC_ID].insert_after.values() for e in es}
    for context in STATE_CONTEXTS:
        for entry in entries(context):
            if entry[COMMAND] not in gen and (entry[COMMAND] in own or not foreign(entry)):
                yield entry


def foreign(entry: dict[str, Any]) -> bool:
    return str(entry[COMMAND]) in foreign_ids()


@cache
def foreign_ids() -> frozenset[str]:
    ids: set[str] = set()
    for mid in (*FOREIGN_REJECT_MODELS, "common"):
        model = raw_models()[mid]
        for patches in (model.insert_before, model.insert_after):
            ids.update(str(e[COMMAND]) for es in patches.values() for e in es)
        ids.update(str(e[COMMAND]) for es in model.contexts.values() for e in es if COMMAND in e)
    return frozenset(ids)


def test_hand_written_entries_cite_an_upstream_file_and_line() -> None:
    seen = 0
    for entry in hand_written():
        prov = entry[PROVENANCE]
        assert str(prov["file"]).startswith(UPSTREAM_PREFIX), entry[COMMAND]
        assert int(prov["line"]) > 0, entry[COMMAND]
        assert "refined_by" not in entry, entry[COMMAND]
        seen += 1
    assert seen >= 7


# --- fixtures ----------------------------------------------------------------------------


@pytest.mark.parametrize("path", fixtures(POS), ids=rel)
def test_pos_fixture_is_accepted(path: Path) -> None:
    assert desc_verdict(path) is True


@pytest.mark.parametrize("path", fixtures(NEG), ids=rel)
def test_neg_fixture_is_rejected(path: Path) -> None:
    assert desc_verdict(path) is False


def gap_params() -> list[Any]:
    return [
        pytest.param(p, id=rel(p), marks=pytest.mark.xfail(strict=True, reason=header(p)["gap"]))
        for p in fixtures(GAP)
    ]


@pytest.mark.parametrize("path", gap_params())
def test_gap_fixture_matches_the_jar(path: Path) -> None:
    assert desc_verdict(path) is False


def test_every_fixture_names_rules_of_the_description_model() -> None:
    known = {c for ctx in models()[DESC_ID].contexts for c in command_ids(ctx)}
    for path in fixtures(POS) + fixtures(NEG) + fixtures(GAP):
        named = {c.strip() for c in header(path)["description"].split(",")}
        assert named <= known, rel(path)


def test_every_reject_entry_has_a_neg_fixture() -> None:
    rejects = {str(e[COMMAND]) for c in STATE_CONTEXTS for e in entries(c) if e.get("reject")}
    covered = {c.strip() for p in fixtures(NEG) for c in header(p)["description"].split(",")}
    assert rejects - foreign_ids() <= covered
    assert {PORT_AT_ROOT, ORPHAN_REJECT, "CommandCreateElementFullForbidden"} <= covered


# --- inline cases (interpreter here, jar in the corpus test) -------------------------

# (body, accepted by the jar). Description-only syntax keeps other factories out.
INLINE_CASES = [
    ("[c]\n}\nnewpage\n[d]", True),
    ("component c {\nnewpage\n}\n[d]", False),
    ("[x]\nx١", True),
    ("[c]\n}\nlegend\nx\nendlegend", True),
    ("component C {\n  together {\n    port p\n  }\n}", True),
    ("together {\n  together {\n    port p\n  }\n}", False),
    ("package P {\n}\n[c]\nport p", False),
    ('domain "G" as g {\n}\n}\n[x]', False),
    ("archimate #red A {\n}\n}\ntitle t", True),
    ("[a]\nportout A [\nx\n]", False),
    ('[a]\nusecase/ U as "x\ny"', True),
]


@pytest.mark.parametrize(("body", "accepted"), INLINE_CASES)
def test_inline_case(body: str, accepted: bool) -> None:
    assert body_verdict(body) is accepted


# Bare words that DESCRIPTION used to take before the single-line factories; with the
# default dispatch the block now reaches the single-line model or fails.
# Expected accepting factory (not model id: single-line family models replace the
# embedded bases over time).
SINGLE_LINE_WORDS = [
    ("license", "PSystemLicenseFactory"),
    ("version", "PSystemVersionFactory"),
    ("licenses", None),
    ("emojis", None),
]


@pytest.mark.parametrize(("word", "factory"), SINGLE_LINE_WORDS)
def test_bare_words_are_left_to_the_single_line_factories(word: str, factory: str | None) -> None:
    resolved = models()
    verdict = accepts(resolved, f"@startuml\n{word}\n@enduml\n")
    accepting = resolved[verdict["model"]].factory if verdict["model"] else None
    assert (verdict["accepted"], accepting) == (factory is not None, factory)


# --- corpus: oracle verdicts ----------------------------------------------------------


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


def oracle_bodies(tmp_path: Path, bodies: list[str]) -> list[bool]:
    from tools.validate.oracle import oracle_verdicts

    paths = []
    for index, body in enumerate(bodies):
        path = tmp_path / f"case{index}.puml"
        path.write_text(f"@startuml\n{body}\n@enduml\n", encoding="utf-8")
        paths.append(path)
    verdicts = oracle_verdicts(paths)
    return [bool(verdicts[str(p)][0]["accepted"]) for p in paths]


@pytest.mark.corpus
def test_inline_cases_equal_the_oracle(tmp_path: Path) -> None:
    bodies = [body for body, _ in INLINE_CASES]
    assert oracle_bodies(tmp_path, bodies) == [accepted for _, accepted in INLINE_CASES]


@pytest.mark.corpus
def test_single_line_words_equal_the_oracle(tmp_path: Path) -> None:
    words = [word for word, _ in SINGLE_LINE_WORDS]
    assert oracle_bodies(tmp_path, words) == [m is not None for _, m in SINGLE_LINE_WORDS]


def corpus_lines(prefix: str) -> Iterator[str]:
    from tools.validate.corpus import enumerate_corpora

    pattern = re.compile(prefix, re.IGNORECASE)
    seen: set[str] = set()
    for _, path, _ in enumerate_corpora():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            text = line.strip()
            if text not in seen and pattern.match(text):
                seen.add(text)
                yield text


@pytest.mark.corpus
def test_port_at_root_only_matches_element_lines() -> None:
    generated = compile_part(gen_entry(CCEF)[PARTS])
    port = compile_part(resolved_variable("D_PORT_ROOT"))
    stray = [t for t in corpus_lines(r"port") if port.fullmatch(t) and not generated.fullmatch(t)]
    assert stray == []
