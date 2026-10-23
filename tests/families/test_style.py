"""``<style>`` blocks (T33, ``model/diagrams/style.yaml``, ``id: style``, ``layer: shared``).

The jar rejects malformed style bodies (StyleParser errors become command errors,
``style/CommandStyleMultilinesCSS.java:92-96``), so ``style`` refines the generated
``CommandStyleMultilinesCSS`` into a ``join`` that matches the whole block with the exact
StyleParser grammar, adds a reject entry for failed blocks, and gives emitters a
``style_body`` context. The model docstring has the details.

Fixtures (``tests/fixtures/style``): multi-block files, a ``' style: <title>`` header
before each block. ``pos/`` is accepted and ``neg/`` + ``gap/`` rejected by the jar
(``corpus`` test). ``gap/`` blocks are known false accepts of the model (see the header
``' gap:`` line); the interpreter accepts them today.

Until diagram models include ``style`` (T16's ``common`` does), every factory's top model
is wrapped in a probe model (``include: [<top>, style]``), as a family model will.
"""

from __future__ import annotations

import os
import re
import subprocess
from functools import cache
from pathlib import Path
from typing import Any

import pytest
import regex
import yaml

from tools.config import PIN_SHA, ConfigError, require
from tools.config import resolve as resolve_config
from tools.interp import accepts
from tools.interp.compile import compile_part
from tools.interp.source import split_blocks
from tools.model import Model, ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve, top_models
from tools.validate.corpus import enumerate_corpora
from tools.validate.oracle import oracle_verdicts

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO / "model"
STYLE_FILE = MODEL_DIR / "diagrams" / "style.yaml"
FIXTURES = REPO / "tests" / "fixtures" / "style"
POS, NEG, GAP = "pos", "neg", "gap"
STYLE_ID = "style"
WRAP_PREFIX = "stylewrap-"
DIAGRAM_LAYER = "diagram"
MAIN = "main"
STYLE_BODY, STYLE_REJECT = "style_body", "style_reject"
MULTILINE = "CommandStyleMultilinesCSS"
SINGLE_LINE = "CommandStyleSingleLineCSS"
REJECT = "CommandStyleMultilinesCSSReject"
STRUCTURE = "CommandStyleMultilinesCSSStructure"
BLOCK_END = "StyleBlockEnd"
GENERATED_BASE = "gen-class-diagram"
CLASS_FACTORY = "ClassDiagramFactory"
JOINER = ""
NBSP = " "
# CommandStyleMultilinesCSS.java:58 END, as the model spells it (no anchors / escapes).
END_CORE = f"[\\s{NBSP}]*</?style>[\\s{NBSP}]*"
UPSTREAM_PREFIX = "src/main/java/net/sourceforge/plantuml/"
HEADER = re.compile(r"^' style: (?P<title>.+)$", re.MULTILINE)
STYLE_START = re.compile(r"<style>", re.IGNORECASE)
STYLE_END = re.compile(END_CORE, re.IGNORECASE)
LONG_BODY_LINES = 2000
TRAILING_LINES = 300
VEGA = "vega"


# ---------------------------------------------------------------- helpers


@cache
def raw_models() -> dict[str, Model]:
    return load_dir(MODEL_DIR)


def wrap_with_style(models: dict[str, Model]) -> dict[str, Model]:
    """Wrap each factory's top model so it includes ``style`` (unless it already does)."""
    resolved = resolve(models)
    wrapped = dict(models)
    for factory, top in top_models(resolved).items():
        if STYLE_ID in resolved[top].includes:
            continue
        wid = WRAP_PREFIX + top
        wrapped[wid] = Model(
            id=wid,
            layer=DIAGRAM_LAYER,
            diagram=models[top].diagram,
            factory=factory,
            include=[top, STYLE_ID],
        )
    return wrapped


@cache
def style_models() -> ResolvedModels:
    return resolve(wrap_with_style(raw_models()))


@cache
def style_doc() -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(STYLE_FILE.read_text(encoding="utf-8"))
    return doc


def fixture_blocks(kind: str) -> list[tuple[str, str]]:
    """``(id, block text)`` for every block of every fixture file of ``kind``."""
    found = []
    for path in sorted((FIXTURES / kind).glob("*.puml")):
        text = path.read_text(encoding="utf-8")
        titles = HEADER.findall(text)
        blocks = split_blocks(text)
        assert len(titles) == len(blocks), f"{path.name}: one header per block"
        found += [(f"{path.stem}: {t}", b) for t, b in zip(titles, blocks, strict=True)]
    return found


def style_regions(lines: list[str]) -> list[tuple[int, int]]:
    """1-based ``(first, last)`` line ranges of ``<style>`` ... END regions."""
    regions, i = [], 0
    while i < len(lines):
        if STYLE_START.fullmatch(lines[i].strip()):
            ends = (j for j in range(i + 1, len(lines)) if STYLE_END.fullmatch(lines[j].strip()))
            j = next(ends, len(lines) - 1)
            regions.append((i + 1, j + 1))
            i = j + 1
        else:
            i += 1
    return regions


def class_top() -> str:
    """Top model of the class factory once ``style`` is included (probe or family)."""
    return top_models(style_models())[CLASS_FACTORY]


def entries_named(command: str) -> list[dict[str, Any]]:
    model = style_models()[class_top()]
    return [e for e in model.contexts[MAIN] if e["command"] == command]


def simple_class(entry: dict[str, Any]) -> str:
    return str(entry["provenance"]["class"]).rsplit(".", 1)[-1]


def hand_written_entries() -> list[dict[str, Any]]:
    doc = style_doc()
    inserted = [e for es in doc["insert_after"].values() for e in es]
    return inserted + [e for es in doc["contexts"].values() for e in es]


# Budget for the long-block tests: they guard against super-linear scans (seconds vs
# minutes), not wall time; the 10 s default flakes when several agents share the CPU.
LONG_BLOCK_TIMEOUT_S = 60.0


def verdict(block: str, timeout_s: float = 10.0) -> dict[str, Any]:
    return dict(accepts(style_models(), block, timeout_s=timeout_s))


def block(*body: str) -> str:
    return "\n".join(["@startuml", *body, "@enduml"])


# ---------------------------------------------------------------- model shape


def test_style_model_is_a_shared_model_with_its_contexts() -> None:
    model = raw_models()[STYLE_ID]
    assert (model.layer, model.diagram, model.path) == ("shared", None, STYLE_FILE)
    assert set(model.contexts) == {STYLE_BODY, STYLE_REJECT}
    assert model.contexts[STYLE_REJECT] == []
    assert set(model.overrides) == {MULTILINE, SINGLE_LINE}
    assert [e["command"] for e in model.insert_after[MULTILINE]] == [REJECT, STRUCTURE]


def test_every_style_multiline_is_refined_and_followed_by_its_inserts() -> None:
    refined = 0
    for model in style_models().values():
        if model.layer != DIAGRAM_LAYER or STYLE_ID not in model.includes:
            continue
        for entries in model.contexts.values():
            names = [e["command"] for e in entries]
            for i, entry in enumerate(entries):
                if simple_class(entry) != MULTILINE or entry["command"] in (REJECT, STRUCTURE):
                    continue
                refined += 1
                assert (entry["kind"], entry.get("refined_by")) == ("multiline", STYLE_ID)
                assert "end" not in entry and entry["join"]["max_lines"] >= LONG_BODY_LINES
                assert names[i + 1 : i + 3] == [REJECT, STRUCTURE]
    assert refined >= 20  # one per command factory (two in list-sprite)


def test_single_line_css_is_refined_in_place() -> None:
    entries = entries_named(SINGLE_LINE)
    assert [(e["kind"], e.get("refined_by")) for e in entries] == [("single", STYLE_ID)]


def test_structure_entry_pushes_body_closed_by_upstream_end() -> None:
    (structure,) = entries_named(STRUCTURE)
    (reject,) = entries_named(REJECT)
    assert (structure["push"], reject["push"]) == (STYLE_BODY, STYLE_REJECT)
    # Upstream multiline form for emitters (nested scopes in TextMate).
    assert (structure["kind"], structure["end"]["regex"]) == ("multiline", END_CORE)
    body = style_models()[class_top()].contexts[STYLE_BODY]
    assert [e["command"] for e in body if e.get("pop")] == [BLOCK_END]


def test_end_pattern_is_the_upstream_end_pattern() -> None:
    generated = yaml.safe_load((MODEL_DIR / "generated" / f"{GENERATED_BASE}.yaml").read_text())
    (entry,) = [e for e in generated["contexts"][MAIN] if e["command"] == MULTILINE]
    upstream = entry["end"]["regex"].strip("^$").replace("\\<", "<").replace("\\>", ">")
    assert upstream == END_CORE
    assert style_doc()["variables"]["STYLE_END_IS_LAST"]["regex"].count(END_CORE) == 2
    (end,) = [e for e in style_doc()["contexts"][STYLE_BODY] if e["command"] == BLOCK_END]
    assert end["parts"]["regex"] == END_CORE


@pytest.mark.parametrize("command", [MULTILINE, REJECT])
def test_join_entries_never_match_a_single_line(command: str) -> None:
    (entry,) = entries_named(command)
    pattern = compile_part(entry["parts"])
    for line in ("<style>", "<style>root{}</style>", "</style>", "root {"):
        assert pattern.fullmatch(line) is None
    assert pattern.fullmatch(f"<style>{JOINER}</style>") is not None


def test_hand_written_rules_cite_upstream_lines() -> None:
    for entry in hand_written_entries():
        prov = entry["provenance"]
        assert prov["file"].startswith(UPSTREAM_PREFIX), entry["command"]
        assert prov["file"].endswith(simple_class(entry) + ".java"), entry["command"]
        assert prov["line"] >= 1


# ---------------------------------------------------------------- fixtures


@pytest.mark.parametrize(("name", "text"), fixture_blocks(POS), ids=lambda v: v[:60])
def test_pos_fixture_is_accepted(name: str, text: str) -> None:
    assert verdict(text)["accepted"] is True, name


@pytest.mark.parametrize(("name", "text"), fixture_blocks(NEG), ids=lambda v: v[:60])
def test_neg_fixture_is_rejected(name: str, text: str) -> None:
    result = verdict(text)
    assert (result["accepted"], result["status"]) == (False, "reject"), name


@pytest.mark.parametrize(("name", "text"), fixture_blocks(GAP), ids=lambda v: v[:60])
def test_gap_fixture_is_a_known_false_accept(name: str, text: str) -> None:
    assert verdict(text)["accepted"] is True, name


def test_neg_fixtures_cover_every_construct_file() -> None:
    pos = {p.stem for p in (FIXTURES / POS).glob("*.puml")}
    neg = {p.stem for p in (FIXTURES / NEG).glob("*.puml")}
    assert pos - neg == {"tags", "braces", "diagrams"}  # unconditionally accepted forms


# ---------------------------------------------------------------- behaviour


def test_rejection_line_is_after_the_style_line() -> None:
    result = verdict(block("<style>", "{", "</style>", "class Foo"))
    assert result["first_failure"] == {"line": 4, "text": "</style>"}


def test_long_body_is_accepted_without_timeout() -> None:
    body = ["root {", *(["LineColor red // c"] * LONG_BODY_LINES), "}"]
    result = verdict(block("<style>", *body, "</style>", "class Foo"), LONG_BLOCK_TIMEOUT_S)
    assert (result["accepted"], result["status"]) == (True, "ok")


def test_unterminated_block_is_rejected_without_timeout() -> None:
    result = verdict(
        block("<style>", "root {", *(["class A"] * TRAILING_LINES)), LONG_BLOCK_TIMEOUT_S
    )
    assert (result["status"], result["first_failure"]["line"]) == ("reject", 4)


def test_without_style_the_generated_models_accept_bad_bodies() -> None:
    only_generated = {"uml": [GENERATED_BASE]}
    bad = block("<style>", "{", "</style>", "class Foo")
    assert accepts(resolve(raw_models()), bad, start_map=only_generated)["accepted"] is True


# ---------------------------------------------------------------- corpus (jar)


def _require(name: str) -> Path:
    try:
        return require(name)
    except ConfigError as err:
        pytest.skip(str(err))


@pytest.mark.corpus
def test_fixtures_agree_with_the_jar() -> None:
    _require("jar")
    files = sorted(FIXTURES.glob("*/*.puml"))
    expected = {POS: True, NEG: False, GAP: False}
    found = oracle_verdicts(files)
    wrong = [
        f"{p.parent.name}/{p.name}#{b['index']}"
        for p in files
        for b in found[str(p)]
        if b["accepted"] is not expected[p.parent.name]
    ]
    assert wrong == []


def _provenances() -> list[tuple[str, int]]:
    generated = [
        e["provenance"]
        for e in style_models()[class_top()].contexts[MAIN]
        if e.get("refined_by") == STYLE_ID
    ]
    own = [e["provenance"] for e in hand_written_entries()]
    return [(p["file"], p["line"]) for p in generated + own]


@pytest.mark.corpus
def test_provenance_lines_exist_at_the_pin() -> None:
    src = _require("src")
    for file, line in _provenances():
        shown = subprocess.run(
            ["git", "-C", str(src), "show", f"{PIN_SHA}:{file}"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert len(shown.stdout.splitlines()) >= line, (file, line)


def _vega_style_files() -> list[Path]:
    cfg = resolve_config(os.environ, Path.home())
    found = enumerate_corpora(cfg, (VEGA,))
    return [p for _, p, _ in found if "<style" in p.read_text(errors="replace").lower()]


@pytest.mark.corpus
def test_no_false_reject_inside_a_style_region_on_vega() -> None:
    _require("jar")
    _require("vega")
    inside = []
    for path, blocks in oracle_verdicts(_vega_style_files()).items():
        for b in (b for b in blocks if b["accepted"]):
            result = verdict("\n".join(b["preproc"]))
            line = (result["first_failure"] or {}).get("line")
            if line and any(a <= line <= z for a, z in style_regions(b["preproc"])):
                inside.append(f"{path}#{b['index']}:{line}")
    assert inside == []


def _corpus_regions() -> dict[str, list[str]]:
    paths = [p for _, p, _ in enumerate_corpora()]
    paths = [p for p in paths if "<style" in p.read_text(errors="replace").lower()]
    regions: dict[str, list[str]] = {}
    for blocks in oracle_verdicts(paths).values():
        for b in blocks:
            for first, last in style_regions(b["preproc"]):
                if STYLE_END.fullmatch(b["preproc"][last - 1].strip()):
                    region = b["preproc"][first - 1 : last]
                    regions.setdefault("\n".join(region), region)
    return regions


@pytest.mark.corpus
def test_every_corpus_style_region_agrees_with_the_jar(tmp_path: Path) -> None:
    _require("jar")
    texts = [block(*region) for region in _corpus_regions().values()]
    files = []
    for i, text in enumerate(texts):
        files.append(tmp_path / f"region-{i}.puml")
        files[-1].write_text(text, encoding="utf-8")
    jar = oracle_verdicts(files)
    wrong = [
        str(f)
        for f, t in zip(files, texts, strict=True)
        if jar[str(f)][0]["accepted"] is not verdict(t)["accepted"]
    ]
    assert (len(texts) > 400, wrong) == (True, [])


def test_style_regions_helper() -> None:
    lines = ["@startuml", "<style>", "a {", "</style>", "x", "<STYLE>", "@enduml"]
    assert style_regions(lines) == [(2, 4), (6, 7)]
    assert regex.fullmatch(END_CORE, f"</style>{NBSP}", regex.IGNORECASE) is not None
