"""Class and object diagrams (T18, ``model/diagrams/class*.yaml``, ``id: class``).

``class`` is the top model of ``ClassDiagramFactory``. It includes the generated model,
``common`` and three shared sub-models (``class-decl``, ``class-objects``,
``class-groups``) and defines one context per diagram state, each running the whole
generated command list after a few head entries (see the model header).

Fixtures (``tests/fixtures/class``), one block each, with a header before ``@start``::

    ' class: RuleA, RuleB      rule ids the fixture exercises
    ' jar: accepted            gap/ only, when the jar accepts (default: rejected)
    ' gap: <reason>            gap/ only: why the model cannot reproduce the jar

``pos/`` is accepted (as CLASS) and ``neg/`` rejected by the jar (``corpus`` test). The
interpreter runs each fixture raw with dispatch restricted to ClassDiagramFactory; the
neg fixtures use class-only syntax so that every other factory rejects them too.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from tools.emit.skip import needs_joiner, skipped
from tools.interp import accepts
from tools.interp.compile import compile_part
from tools.interp.source import split_blocks
from tools.model import Model, ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve, top_models

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO / "model"
FIXTURES = REPO / "tests" / "fixtures" / "class"
POS, NEG, GAP = "pos", "neg", "gap"
CLASS_ID = "class"
GEN_ID = "gen-class-diagram"
SUB_MODELS = ("class-decl", "class-objects", "class-groups")
FACTORY = "ClassDiagramFactory"
DIAGRAM = "CLASS"
MAIN = "main"
STATE_CONTEXTS = ("main", "main_mixing", "class_group", "class_group_mixing", "class_orphan")
BODY_CONTEXTS = ("class_body", "object_body", "map_body")
START_MAP = {"uml": [FACTORY]}
JAR_ACCEPTED = "accepted"
UPSTREAM_PREFIX = "src/main/java/"
HEADER = re.compile(r"^' (?P<key>class|jar|gap): (?P<value>.+)$")
COMMAND, PROVENANCE = "command", "provenance"


@cache
def raw_models() -> dict[str, Model]:
    return load_dir(MODEL_DIR)


@cache
def models() -> ResolvedModels:
    return resolve(raw_models())


def entries(context: str) -> list[dict[str, Any]]:
    return list(models()[CLASS_ID].contexts[context])


def command_ids(context: str) -> list[str]:
    return [str(e[COMMAND]) for e in entries(context)]


def gen_entry(command: str) -> dict[str, Any]:
    return next(e for e in models()[GEN_ID].contexts[MAIN] if e[COMMAND] == command)


def class_entry(context: str, command: str) -> dict[str, Any]:
    return next(e for e in entries(context) if e[COMMAND] == command)


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


def class_verdict(path: Path) -> bool:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    return bool(accepts(models(), block, raw=True, start_map=START_MAP)["accepted"])


def body_verdict(body: str) -> bool:
    block = f"@startuml\n{body}\n@enduml\n"
    return bool(accepts(models(), block, start_map=START_MAP)["accepted"])


# --- model shape -----------------------------------------------------------------------


def test_class_is_the_top_model_of_the_class_factory() -> None:
    model = models()[CLASS_ID]
    assert top_models(models())[FACTORY] == CLASS_ID
    assert (model.layer, model.diagram, model.factory) == ("diagram", DIAGRAM, FACTORY)
    assert set(model.includes) >= {GEN_ID, "common", *SUB_MODELS}


def test_sub_models_are_shared_files_next_to_the_class_model() -> None:
    for mid in SUB_MODELS:
        model = raw_models()[mid]
        assert model.layer == "shared"
        assert model.path.parent == MODEL_DIR / "diagrams"


@pytest.mark.parametrize("context", STATE_CONTEXTS)
def test_every_state_runs_the_generated_list_in_upstream_order(context: str) -> None:
    generated = [str(e[COMMAND]) for e in models()[GEN_ID].contexts[MAIN]]
    present = [c for c in command_ids(context) if c in set(generated)]
    assert present == generated


def test_class_declaration_enters_the_class_body() -> None:
    entry = class_entry(MAIN, "CommandCreateClassMultilines")
    assert (entry["kind"], entry["push"], entry["require_pop"]) == ("single", "class_body", True)
    assert entry["refined_by"] == "class-decl"


@pytest.mark.parametrize(
    ("command", "body"),
    [
        ("CommandCreateEntityObjectMultilines", "object_body"),
        ("CommandCreateMap", "map_body"),
    ],
)
def test_object_and_map_bodies_are_contexts(command: str, body: str) -> None:
    entry = class_entry(MAIN, command)
    assert (entry["kind"], entry["push"], entry["require_pop"]) == ("single", body, True)


@pytest.mark.parametrize(
    "command",
    [
        "CommandCreateClassMultilinesBracketNextLine",
        "CommandPackageBracketNextLine",
        "CommandCreateJsonBlock",
        "GatePackageBracketNextLine",
    ],
)
def test_multi_line_joins_are_invisible_to_emitters(command: str) -> None:
    entry = next(e for c in STATE_CONTEXTS for e in entries(c) if e[COMMAND] == command)
    assert needs_joiner(entry["parts"]) is True
    assert skipped(entry) is True


def test_rejects_precede_the_rule_they_shadow() -> None:
    ids = command_ids(MAIN)
    for reject, rule in [
        ("CommandCreateClassMultilinesBadSpotColor", "CommandCreateClassMultilines"),
        ("CommandCreateClassBadSpotColor", "CommandCreateClass"),
        ("CommandPackageEmptyName", "CommandPackage"),
        ("CommandCreateJsonError", "CommandCreateJson"),
        ("CommandCreateJsonSingleLineError", "CommandCreateJsonSingleLine"),
    ]:
        assert ids.index(reject) == ids.index(rule) - 1


def hand_written() -> Iterator[dict[str, Any]]:
    gen = {str(e[COMMAND]) for e in models()[GEN_ID].contexts[MAIN]}
    for context in (*STATE_CONTEXTS, *BODY_CONTEXTS):
        yield from (e for e in entries(context) if e[COMMAND] not in gen)


def test_hand_written_entries_cite_an_upstream_file_and_line() -> None:
    for entry in hand_written():
        prov = entry[PROVENANCE]
        assert str(prov["file"]).startswith(UPSTREAM_PREFIX), entry[COMMAND]
        assert int(prov["line"]) > 0, entry[COMMAND]
        assert "refined_by" not in entry, entry[COMMAND]


def test_spot_color_names_are_the_shared_color_table() -> None:
    shared = raw_models()["shared"].variables
    names = [
        a["literal"] for v in ("COLOR_NAME", "COLOR_SPECIAL") for a in shared[v]["seq"][0]["alt"]
    ]
    pattern = str(raw_models()["class-decl"].variables["CD_STEREO_BAD_SPOT"]["regex"])
    listed = re.search(r"\(\?!\(\?:(?P<names>[A-Za-z|]+)\|\[0-9a-f\]\{8\}", pattern)
    assert listed is not None
    assert listed["names"].split("|") == names


# --- fixtures ----------------------------------------------------------------------------


@pytest.mark.parametrize("path", fixtures(POS), ids=rel)
def test_pos_fixture_is_accepted(path: Path) -> None:
    assert class_verdict(path) is True


@pytest.mark.parametrize("path", fixtures(NEG), ids=rel)
def test_neg_fixture_is_rejected(path: Path) -> None:
    assert class_verdict(path) is False


def gap_params() -> list[Any]:
    return [
        pytest.param(p, id=rel(p), marks=pytest.mark.xfail(strict=True, reason=header(p)["gap"]))
        for p in fixtures(GAP)
    ]


@pytest.mark.parametrize("path", gap_params())
def test_gap_fixture_matches_the_jar(path: Path) -> None:
    assert class_verdict(path) is jar_accepts(path)


def test_every_fixture_names_rules_of_the_class_model() -> None:
    known = {c for ctx in models()[CLASS_ID].contexts for c in command_ids(ctx)}
    for path in fixtures(POS) + fixtures(NEG) + fixtures(GAP):
        named = {c.strip() for c in header(path)["class"].split(",")}
        assert named <= known, rel(path)


def test_every_reject_entry_has_a_neg_fixture() -> None:
    rejects = {str(e[COMMAND]) for c in STATE_CONTEXTS for e in entries(c) if e.get("reject")}
    covered = {c.strip() for p in fixtures(NEG) for c in header(p)["class"].split(",")}
    exempt = common_rejects()
    assert rejects - exempt <= covered


def common_rejects() -> set[str]:
    """Rejects contributed by common-errors (T16 has their fixtures)."""
    errors = raw_models()["common-errors"]
    return {str(e[COMMAND]) for es in errors.insert_after.values() for e in es}


# --- inline cases (interpreter here, jar in the corpus test) -------------------------

# (body, accepted by the jar). Class-only syntax keeps other factories out.
INLINE_CASES = [
    ('class X\njson J {\n"a": [1, {"b": null}],\n"c": "d"\n}', True),
    ("class X\njson J {\n}", True),
    ('class X\njson J {\n"a": 1,\n}', False),
    ('class X\njson J {\n"a": tru\ne\n}', True),
    ('class X\njson J {\n"a": 1\n2\n}', True),
    ('class X\njson J {\n{"a": 1}\n}', True),
    ('class X\njson J {\n"a": "x\\u00e9"\n}', True),
    ('class X\njson J {\n"a": "x\\q"\n}', False),
    ("class X\njson J -0", True),
    ("class X\njson J 1.5", False),
    ('class X\njson J {"a":1} ', True),
    ("class X\nmap M {\n}", True),
    ("class X\nmap M {\n a *--> X\n}", True),
    ("class X {\n  {{\n  }\n  }}\n}", True),
    ("class X {\n  {{\n  }\n}", False),
    ("class X {\n}\nnamespace n {\n}\n}", True),
    ("class X {\n}\ntogether {\n}\n}\nnote as N", False),
    ("class X {\n}\nnode N {\n}\n}\ncaption c", True),
    ("class X {\n}\nallowmixing\nnode N {\n  node M {\n    actor Bob\n  }\n}", True),
]


@pytest.mark.parametrize(("body", "accepted"), INLINE_CASES)
def test_inline_case(body: str, accepted: bool) -> None:
    assert body_verdict(body) is accepted


# --- corpus: oracle verdicts and structured copies -----------------------------------


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


def variable(name: str) -> dict[str, Any]:
    return dict(models()[CLASS_ID].variables[name])


def ref_seq(*names: str, tail: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"seq": [variable(n) for n in names] + (tail or [])}


BRACE_TAIL = [{"literal": "{", "ci": True}]
SPACES = {"regex": "[\\s ]*", "ci": True}

# (generated rule, structured copy, cheap prefix filter for corpus lines)
COPIES = [
    (
        "CommandCreateClassMultilines",
        lambda: ref_seq("CD_CLASS_HEAD", tail=[*BRACE_TAIL, SPACES]),
        r"[-#+~]?\s*(?:abstract|static|class|interface|enum|annotation|entity|protocol|struct|exception|metaclass|stereotype|dataclass|record)\b",
    ),
    ("CommandPackage", lambda: ref_seq("CD_PACKAGE_HEAD", tail=BRACE_TAIL), r"[-#+~]?\s*package\b"),
    ("CommandCreateElementFull2_30", lambda: variable("CG_ELEMENT_FULL2"), r"\w"),
    ("CommandCreateJson", lambda: variable("CO_JSON_HEAD"), r"json\b"),
]


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
@pytest.mark.parametrize(("command", "copy", "prefix"), COPIES, ids=[c[0] for c in COPIES])
def test_structured_copy_accepts_what_the_generated_rule_accepts(
    command: str, copy: Any, prefix: str
) -> None:
    generated = compile_part(gen_entry(command)["parts"])
    structured = compile_part(copy())
    differ = [
        t
        for t in corpus_lines(prefix)
        if bool(generated.fullmatch(t)) != bool(structured.fullmatch(t))
    ]
    assert differ == []
