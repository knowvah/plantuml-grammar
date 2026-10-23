"""Commands shared by command-based diagrams (T16, ``model/diagrams/common.yaml``).

``CommonCommands.java:55-127`` (97a5992) registers the same block in every command
factory; the generated models already carry it in upstream order. ``common`` (``layer:
shared``) refines those entries in place with ``overrides`` / ``insert_before`` and adds
the body contexts they push, so every diagram model that includes ``common`` gets them.

Fixtures (``tests/fixtures/common``), each with a header before ``@start``::

    ' common: CommandA, CommandB          rule ids the fixture exercises
    ' factory: SequenceDiagramFactory     factory the run is restricted to
    ' gap: <reason>                       gap/ only: why the model cannot reject it yet

``pos/`` is accepted and ``neg/`` + ``gap/`` rejected by the jar (``corpus`` test).
The interpreter runs each fixture raw with dispatch restricted to the header factory:
the jar rejects only when every factory rejects, and an accepted fixture names the
factory through the oracle diagram type, so the restricted verdict must match. Full
dispatch also reaches family models (description and class accept bare words the jar
rejects), which is not a property of the common commands.

Until family models include ``common``, each command factory's top model is wrapped in
a probe model (``include: [<top>, common]``), exactly what a family model will do.
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
from tools.model.resolve import resolve, top_models

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO / "model"
COMMON_FILE = MODEL_DIR / "diagrams" / "common.yaml"
FIXTURES = REPO / "tests" / "fixtures" / "common"
POS, NEG, GAP = "pos", "neg", "gap"
COMMON_ID = "common"
ERRORS_ID = "common-errors"
SHARED_ID = "shared"
MAIN = "main"
DIAGRAM_LAYER = "diagram"
PROBE_PREFIX = "probe-"
SEQUENCE_FACTORY = "SequenceDiagramFactory"
UPSTREAM_PREFIX = "src/main/java/net/sourceforge/plantuml/"
HEADER = re.compile(r"^' (?P<key>common|factory|gap): (?P<value>.+)$")
START = re.compile(r"^@start(?P<keyword>\w+)", re.MULTILINE)

# Rule ids of the common block, CommonCommands.java:113-126 (titles), :63-93 (commands2),
# :98-103 (scale), :107-109 (hides). `CommandFactorySprite_1/_2` are the anonymous
# classes `CommandFactorySprite$1/$2` created at :77-78.
COMMON_COMMANDS = (
    "CommandTitle CommandMainframe CommandCaption CommandMultilinesCaption "
    "CommandMultilinesTitle CommandMultilinesLegend CommandLegend CommandFooter "
    "CommandMultilinesFooter CommandHeader CommandMultilinesHeader CommandNamespaceSeparator "
    "CommandNope CommandPragma CommandAssumeTransparent CommandSkinParam CommandSkinParamJaws "
    "CommandSkinParamMultilines CommandSkin CommandMinwidth CommandPage CommandRotate "
    "CommandFactorySprite_1 CommandFactorySprite_2 CommandSpriteBase64 CommandSpriteMd5 "
    "CommandSpriteSvg CommandSpriteStdlib CommandSpriteStdlibSvg CommandSpriteSvgMultiline "
    "CommandSpriteFile CommandStyleSingleLineCSS CommandStyleMultilinesCSS CommandStyleImport "
    "CommandScale CommandScaleWidthAndHeight CommandScaleWidthOrHeight CommandScaleMaxWidth "
    "CommandScaleMaxHeight CommandScaleMaxWidthAndHeight CommandHideEmptyDescription "
    "CommandHideShowByVisibility CommandHideShowByGender"
).split()
NO_NEG_FIXTURE = {
    "CommandNope": "matches every blank line (CommandNope.java:54); no input reaches it "
    "and is rejected",
}


def simple_key(entry: dict[str, Any]) -> str:
    """Patch key of an entry's provenance class (`Outer$1` -> `Outer_1`)."""
    return str(entry["provenance"]["class"]).rsplit(".", 1)[-1].replace("$", "_")


def has_common_block(model: ResolvedModel) -> bool:
    return any(simple_key(e) in COMMON_COMMANDS for e in model.contexts.get(MAIN, []))


def with_probes(raw: dict[str, Model]) -> dict[str, Model]:
    """Wrap every top command-factory model that does not include ``common`` yet."""
    resolved = resolve(raw)
    out = dict(raw)
    for factory, mid in top_models(resolved).items():
        top = resolved[mid]
        if COMMON_ID in top.includes or not has_common_block(top):
            continue
        pid = PROBE_PREFIX + mid
        out[pid] = Model(
            id=pid,
            layer=DIAGRAM_LAYER,
            diagram=top.diagram,
            factory=factory,
            include=[mid, COMMON_ID],
        )
    return out


@pytest.fixture(scope="module")
def raw_models() -> dict[str, Model]:
    return load_dir(MODEL_DIR)


@pytest.fixture(scope="module")
def models(raw_models: dict[str, Model]) -> ResolvedModels:
    return resolve(with_probes(raw_models))


def fixtures(group: str) -> list[Path]:
    return sorted((FIXTURES / group).glob("*.puml"))


def header(path: Path) -> dict[str, str]:
    found = (HEADER.match(line) for line in path.read_text(encoding="utf-8").splitlines())
    return {m["key"]: m["value"] for m in found if m}


def fixture_commands(path: Path) -> list[str]:
    return [c.strip() for c in header(path)["common"].split(",")]


def restricted_verdict(models: ResolvedModels, path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    keyword = START.search(text)
    assert keyword, path
    start_map = {keyword["keyword"]: [header(path)["factory"]]}
    (block,) = split_blocks(text)
    return accepts(models, block, raw=True, start_map=start_map)


def factory_diagram(models: ResolvedModels, factory: str) -> str | None:
    return models[top_models(models)[factory]].diagram


def rel(path: Path) -> str:
    return path.relative_to(FIXTURES).as_posix()


# --- the model ------------------------------------------------------------------------


def test_common_is_a_shared_model_in_the_diagrams_folder(raw_models: dict[str, Model]) -> None:
    common = raw_models[COMMON_ID]
    assert (common.layer, common.diagram, common.path) == ("shared", None, COMMON_FILE)
    assert SHARED_ID in common.include


def own_models(raw: dict[str, Model]) -> list[Model]:
    """The T16 models: ``common`` and ``common-errors``."""
    return [raw[COMMON_ID], raw[ERRORS_ID]]


def test_patch_keys_are_common_rule_ids(raw_models: dict[str, Model]) -> None:
    for model in own_models(raw_models):
        keys = set(model.overrides) | set(model.insert_before) | set(model.insert_after)
        assert keys and keys <= set(COMMON_COMMANDS), model.id


def inserted_entries(model: Model) -> list[dict[str, Any]]:
    groups = (model.insert_before, model.insert_after)
    return [e for group in groups for entries in group.values() for e in entries]


def context_entries(model: Model) -> list[dict[str, Any]]:
    return [e for entries in model.contexts.values() for e in entries]


def test_hand_written_entries_cite_upstream_file_and_line(raw_models: dict[str, Model]) -> None:
    models = own_models(raw_models)
    entries = [e for m in models for e in inserted_entries(m) + context_entries(m)]
    assert len(entries) >= 20
    for entry in entries:
        prov = entry["provenance"]
        assert prov["file"].startswith(UPSTREAM_PREFIX), entry["command"]
        assert prov["line"] >= 1, entry["command"]
        assert all(a.startswith(UPSTREAM_PREFIX) for a in prov.get("also", [])), entry["command"]


def test_context_entries_do_not_cite_a_patched_class(raw_models: dict[str, Model]) -> None:
    # A class-name patch key matches every entry citing that class, contexts included.
    for model in own_models(raw_models):
        for entry in context_entries(model):
            assert simple_key(entry) not in COMMON_COMMANDS, entry["command"]


def test_each_reject_directly_follows_its_narrowed_rule(
    raw_models: dict[str, Model], models: ResolvedModels
) -> None:
    errors = raw_models[ERRORS_ID].insert_after
    assert all(e.get("reject") for entries in errors.values() for e in entries)
    main = [e["command"] for e in common_top(models, SEQUENCE_FACTORY).contexts[MAIN]]
    for key, entries in errors.items():
        (entry,) = entries
        assert main[main.index(key) + 1] == entry["command"], key


def probe_pairs(models: ResolvedModels) -> list[tuple[ResolvedModel, ResolvedModel]]:
    return [
        (m, models[m.id.removeprefix(PROBE_PREFIX)])
        for m in models.values()
        if m.id.startswith(PROBE_PREFIX)
    ]


def common_top(models: ResolvedModels, factory: str) -> ResolvedModel:
    """Top model of ``factory``: its probe, or the family model that includes ``common``."""
    top = models[top_models(models)[factory]]
    assert COMMON_ID in top.includes, factory
    return top


def test_every_command_factory_with_the_common_block_includes_common(
    models: ResolvedModels,
) -> None:
    tops = [models[mid] for mid in top_models(models).values()]
    covered = {m.factory for m in tops if COMMON_ID in m.includes}
    assert {SEQUENCE_FACTORY, "ClassDiagramFactory", "GanttDiagramFactory"} <= covered
    assert len(covered) >= 20


def test_probes_keep_the_upstream_order_of_the_base_model(
    raw_models: dict[str, Model], models: ResolvedModels
) -> None:
    # Inserts of `common` and of the shared models it includes (e.g. `style`, T33).
    sources = [raw_models[mid] for mid in (COMMON_ID, *models[COMMON_ID].includes)]
    inserted = {
        e["command"]
        for src in sources
        for group in (src.insert_before, src.insert_after)
        for entries in group.values()
        for e in entries
    }
    for probe, base in probe_pairs(models):
        kept = [e["command"] for e in probe.contexts[MAIN] if e["command"] not in inserted]
        assert kept == [e["command"] for e in base.contexts[MAIN]], probe.id


def test_refined_entries_are_marked_refined_by_common(
    raw_models: dict[str, Model], models: ResolvedModels
) -> None:
    keys = set(raw_models[COMMON_ID].overrides)
    top = common_top(models, SEQUENCE_FACTORY)
    refined = {e["command"] for e in top.contexts[MAIN] if e.get("refined_by") == COMMON_ID}
    assert refined == keys


def test_body_contexts_reach_every_probe(models: ResolvedModels) -> None:
    for probe, _ in probe_pairs(models):
        assert {"skinparam_body", "sprite_gray16_first"} <= set(probe.contexts), probe.id


# --- fixtures -------------------------------------------------------------------------


@pytest.mark.parametrize("path", fixtures(POS), ids=rel)
def test_pos_fixture_is_accepted_by_the_header_factory(models: ResolvedModels, path: Path) -> None:
    verdict = restricted_verdict(models, path)
    assert verdict["accepted"], verdict["first_failure"]
    assert verdict["diagram"] == factory_diagram(models, header(path)["factory"])


@pytest.mark.parametrize("path", fixtures(NEG), ids=rel)
def test_neg_fixture_is_rejected_by_the_header_factory(models: ResolvedModels, path: Path) -> None:
    assert restricted_verdict(models, path)["accepted"] is False


def gap_params() -> list[Any]:
    return [
        pytest.param(p, id=rel(p), marks=pytest.mark.xfail(strict=True, reason=header(p)["gap"]))
        for p in fixtures(GAP)
    ]


@pytest.mark.parametrize("path", gap_params())
def test_gap_fixture_is_rejected_by_the_header_factory(models: ResolvedModels, path: Path) -> None:
    assert restricted_verdict(models, path)["accepted"] is False


@pytest.mark.parametrize("path", fixtures(POS), ids=rel)
def test_pos_fixture_is_accepted_with_full_dispatch(models: ResolvedModels, path: Path) -> None:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    assert accepts(models, block, raw=True)["accepted"]


def test_every_fixture_names_known_commands_and_a_factory(models: ResolvedModels) -> None:
    tops = top_models(models)
    for path in fixtures(POS) + fixtures(NEG) + fixtures(GAP):
        assert set(fixture_commands(path)) <= set(COMMON_COMMANDS), rel(path)
        assert header(path)["factory"] in tops, rel(path)


@pytest.mark.parametrize("group", [POS, NEG])
def test_every_common_command_has_a_fixture(group: str) -> None:
    covered = {c for path in fixtures(group) for c in fixture_commands(path)}
    exempt = set(NO_NEG_FIXTURE) if group == NEG else set()
    assert set(COMMON_COMMANDS) - exempt <= covered


@pytest.mark.corpus
def test_fixture_verdicts_equal_the_oracle(models: ResolvedModels) -> None:
    from tools.validate.oracle import oracle_verdicts

    paths = fixtures(POS) + fixtures(NEG) + fixtures(GAP)
    verdicts = oracle_verdicts(paths)
    for path in paths:
        (block,) = verdicts[str(path)]
        assert block["accepted"] is (path.parent.name == POS), rel(path)
        if block["accepted"]:
            assert block["diagram_type"] == factory_diagram(models, header(path)["factory"])


# --- refined fragments ----------------------------------------------------------------


def variable(models: ResolvedModels, name: str) -> Any:
    return compile_part(models[COMMON_ID].variables[name])


@pytest.mark.parametrize(
    ("name", "text", "matches"),
    [
        ("JAVA_INT", "0", True),
        ("JAVA_INT", "000123", True),
        ("JAVA_INT", "2147483647", True),
        ("JAVA_INT", "02147483647", True),
        ("JAVA_INT", "2147483648", False),
        ("JAVA_INT", "99999999999", False),
        ("JAVA_INT", "-1", False),
        ("JAVA_INT_POSITIVE", "0", False),
        ("JAVA_INT_POSITIVE", "007", True),
        ("JAVA_INT_POSITIVE", "1999999999", True),
        ("JAVA_DOUBLE", "1.", True),
        ("JAVA_DOUBLE", ".5", True),
        ("JAVA_DOUBLE", "0", True),
        ("JAVA_DOUBLE", ".", False),
        ("JAVA_DOUBLE", "1.2.3", False),
        ("JAVA_DOUBLE_NONZERO", "0.00", False),
        ("JAVA_DOUBLE_NONZERO", "0.01", True),
        ("SPRITE_GRAY16_DATA", "0aF9", True),
        ("SPRITE_GRAY16_DATA", "Ａ٣", True),
        ("SPRITE_GRAY16_DATA", "FG", False),
        ("SPRITE_GRAY16_DATA", "F F", False),
        ("SPRITE_DATA_LINE", "zz!!", True),
        ("SPRITE_DATA_LINE", "end sprite", False),
        ("SPRITE_DATA_LINE", "}", False),
        ("SKINPARAM_SETTING", "ArrowColor red", True),
        ("SKINPARAM_SETTING", "participant<<Foo>>BackgroundColor red", True),
        ("SKINPARAM_SETTING", "ArrowColor:red", False),
        ("SKINPARAM_SETTING", "red", False),
    ],
)
def test_refined_fragment(models: ResolvedModels, name: str, text: str, matches: bool) -> None:
    assert (variable(models, name).fullmatch(text) is not None) is matches
