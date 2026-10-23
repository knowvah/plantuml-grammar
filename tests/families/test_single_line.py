"""Single-line and novelty diagram types (T34, ``model/diagrams/single-line*.yaml``).

* ``single-line-<type>`` refines each ``PSystemSingleLineFactory`` model (embedded or
  generated): noise and the command line are matched untrimmed, the block must be exactly
  one line after noise (``single-line-base``).
* ``single-line-help`` / ``single-line-crash`` refine the two small command factories.
* ``single-line-{ditaa,math,latex}`` (with ``single-line-basic``) and ``single-line-dot``
  refine the D4 ``PSystemBasicFactory`` bodies: unparsed, but counted like upstream.

Fixtures (``tests/fixtures/single-line``) carry ``' single-line: <model id>`` (the model
that accepts a ``pos`` fixture) and, in ``gap/``, ``' gap: <reason>``. ``pos/`` and ``gap/``
are accepted by the jar, ``neg/`` rejected (``corpus`` test). The interpreter runs each
fixture raw with full dispatch.
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
from tools.model import Model, ResolvedModel, ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve, top_models

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO / "model"
FIXTURES = REPO / "tests" / "fixtures" / "single-line"
POS, NEG, GAP = "pos", "neg", "gap"
PREFIX = "single-line-"
HEADER = re.compile(r"^' (?P<key>single-line|gap): (?P<value>.+)$")
UPSTREAM_PREFIX = "src/main/java/net/sourceforge/plantuml/"
SINGLE_LINE = {
    "PSystemLicenseFactory": "license",
    "PSystemVersionFactory": "version",
    "PSystemDonorsFactory": "donors",
    "PSystemSkinparameterListFactory": "skinparameter-list",
    "PSystemListFontsFactory": "list-fonts",
    "PSystemListEmojiFactory": "list-emoji",
    "PSystemOpenIconicFactory": "open-iconic",
    "PSystemListOpenIconicFactory": "list-open-iconic",
    "PSystemListArchimateSpritesFactory": "list-archimate-sprites",
    "PSystemAppleTwoFactory": "apple-two",
    "PSystemRIPFactory": "rip",
    "PSystemCharlieFactory": "charlie",
    "PSystemDedicationFactory": "dedication",
    "PSystemColorsFactory": "colors",
    "PSystemSudokuFactory": "sudoku",
}
OTHER = {
    "HelpFactory": "help",
    "CrashDiagramFactory": "crash",
    "PSystemDitaaFactory": "ditaa",
    "PSystemMathFactory": "math",
    "PSystemLatexFactory": "latex",
    "PSystemDotFactory": "dot",
}
UNCHANGED = {"PSystemWelcomeFactory": "embedded-welcome", "PSystemEggFactory": "embedded-egg"}
LONG_MAX = 2**63 - 1
BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"
SAMPLES = 3000
DEDICATION_MIN = 26  # Dedications.java:92, line.length() > 25
SENTENCES = [  # dedication/Dedications.java:55-65
    "Write your own dedication!",
    "linux_china",
    "arkban",
    "Boundaries allow discipline to create true strength",
    "Thank you, Dr. Chet. I wouldn't be where I am without you",
    "Ben and Jen 2020",
    "baraye",
    "Nothing of value is ever easy",
    "Have good friends and be a good friend to other people",
    "By the time a man realizes that maybe his father was right, he usually has a son who"
    " thinks he is wrong",
]
# Chars whose Java case mapping lands on an ASCII letter (plus decoys).
CASE_ODDITIES = "ıİſKÅéß"
SEPARATORS = [" ", "!", "_", "\t", "😀", "٣", "—", ""]


@pytest.fixture(scope="module")
def raw_models() -> dict[str, Model]:
    return load_dir(MODEL_DIR)


@pytest.fixture(scope="module")
def models(raw_models: dict[str, Model]) -> ResolvedModels:
    return resolve(raw_models)


def entry(model: ResolvedModel, command: str) -> dict[str, Any]:
    return next(e for ctx in model.contexts.values() for e in ctx if e["command"] == command)


def matcher(model: ResolvedModel, command: str) -> regex.Pattern[str]:
    return compile_part(entry(model, command)["parts"])


def commands(model: ResolvedModel, context: str) -> list[str]:
    return [e["command"] for e in model.contexts[context]]


# --- structure ------------------------------------------------------------------------


def test_family_models_are_the_top_models(models: ResolvedModels) -> None:
    tops = top_models(models)
    wanted = {f: PREFIX + name for f, name in (SINGLE_LINE | OTHER).items()} | UNCHANGED
    assert {f: tops[f] for f in wanted} == wanted


@pytest.mark.parametrize("factory", sorted(SINGLE_LINE))
def test_single_line_main_is_noise_blank_then_the_untrimmed_command(
    models: ResolvedModels, factory: str
) -> None:
    model = models[PREFIX + SINGLE_LINE[factory]]
    assert commands(model, "main") == ["UmlSourceNoise", "SingleLineBlankLine", factory]
    command = entry(model, factory)
    assert (command["trim"], command["set"], command["gives"]) == (False, "sl_done", "single_line")
    assert entry(model, "UmlSourceNoise")["needs"] == "single_line"
    assert commands(model, "sl_done") == ["SingleLineExtraLine"]


@pytest.mark.parametrize("name", ["ditaa", "math", "latex"])
def test_basic_bodies_count_lines_like_the_basic_factory(models: ResolvedModels, name: str) -> None:
    model = models[PREFIX + name]
    assert commands(model, "main")[:2] == ["BasicNoise", "BasicBlankLine"]
    assert commands(model, "empty") == ["BasicEmptyBlankLine", "BasicEmptyEnd"]
    body = model.contexts["main"][2]
    assert (body["kind"], body["gives"]) == ("single", "basic_line")


def test_truncated_welcome_block_is_rejected(models: ResolvedModels) -> None:
    # A preprocessor-truncated `@startuml` has one source line; PSystemWelcomeFactory.java:52
    # needs exactly two, and every command factory reports an empty description.
    verdict = accepts(models, "@startuml", raw=True)
    assert (verdict["accepted"], verdict["first_failure"]["line"]) == (False, 1)  # type: ignore[index]
    assert accepts(models, "@startuml\n@enduml", raw=True)["model"] == "embedded-welcome"


@pytest.mark.parametrize("name", ["ditaa", "math", "latex"])
def test_truncated_basic_block_stays_accepted(models: ResolvedModels, name: str) -> None:
    # PSystemBasicFactory.createSystem returns the system when the iterator runs out (:101).
    verdict = accepts(models, f"@start{name}", raw=True)
    assert (verdict["accepted"], verdict["model"]) == (True, PREFIX + name)


def hand_written_entries(model: Model) -> list[dict[str, Any]]:
    """Override patches, inserted entries and context entries of one model file."""
    found: list[dict[str, Any]] = list(model.overrides.values())
    for group in (model.insert_before, model.insert_after):
        found += [e for entries in group.values() for e in entries]
    return found + [e for ctx in model.contexts.values() for e in ctx]


def test_hand_written_entries_cite_upstream_file_and_line(raw_models: dict[str, Model]) -> None:
    family = [m for model_id, m in raw_models.items() if model_id.startswith(PREFIX)]
    cited = [e["provenance"] for m in family for e in hand_written_entries(m) if "provenance" in e]
    assert len(family) == len(SINGLE_LINE) + len(OTHER) + 2  # + base and basic (shared)
    assert all(p["file"].startswith(UPSTREAM_PREFIX) and p["line"] > 0 for p in cited)


# --- regexes against Java semantics -------------------------------------------------


def test_sudoku_seed_is_bounded_by_long_max_value(models: ResolvedModels) -> None:
    pattern = matcher(models[PREFIX + "sudoku"], "PSystemSudokuFactory")
    rng = random.Random(34)
    seeds = [_base36(LONG_MAX), _base36(LONG_MAX + 1), "0" * 30 + _base36(LONG_MAX)]
    for _ in range(SAMPLES):
        seeds.append(_base36(rng.randint(LONG_MAX - 10**16, LONG_MAX + 10**16)))
        seeds.append("".join(rng.choice(BASE36) for _ in range(rng.randint(1, 15))))
    for seed in seeds:
        line = f"sudoku {seed.upper() if rng.random() < 0.3 else seed}"
        assert (pattern.fullmatch(line) is not None) is (int(seed, 36) <= LONG_MAX), line


def _base36(value: int) -> str:
    digits = ""
    while value:
        value, rest = divmod(value, 36)
        digits = BASE36[rest] + digits
    return digits or "0"


def _java_upper(ch: str) -> str:
    up = ch.upper()
    return up if len(up) == 1 else ch


def _java_lower(ch: str) -> str:
    return ch.lower()[0]


def java_equals_ignore_case(a: str, b: str) -> bool:
    """``String.equalsIgnoreCase`` / ``regionMatches(true, ...)`` char by char."""
    if len(a) != len(b):
        return False
    for x, y in zip(a, b, strict=True):
        ux, uy = _java_upper(x), _java_upper(y)
        if x != y and ux != uy and _java_lower(ux) != _java_lower(uy):
            return False
    return True


def java_dedication(line: str) -> bool:
    """``Dedications.get`` restricted to the DedicationSimple sentences."""
    if len(line.encode("utf-16-le")) // 2 < DEDICATION_MIN:
        return False
    strip = regex.compile(r"[^\p{L}0-9]+")
    return any(java_equals_ignore_case(strip.sub("", s), strip.sub("", line)) for s in SENTENCES)


def _variant(rng: random.Random, sentence: str) -> str:
    out = []
    for ch in sentence:
        if ch.isalpha() and rng.random() < 0.3:
            ch = rng.choice([ch.upper(), ch.lower(), *CASE_ODDITIES])
        out.append(ch + (rng.choice(SEPARATORS) if rng.random() < 0.2 else ""))
    if rng.random() < 0.1 and len(out) > 1:
        del out[rng.randrange(len(out))]
    return "".join(out) + rng.choice(SEPARATORS) * rng.randint(0, 25)


def test_dedication_matches_the_java_sentence_comparison(models: ResolvedModels) -> None:
    pattern = matcher(models[PREFIX + "dedication"], "PSystemDedicationFactory")
    rng = random.Random(25)
    for _ in range(SAMPLES):
        line = _variant(rng, rng.choice(SENTENCES))
        assert (pattern.fullmatch(line) is not None) is java_dedication(line), repr(line)


@pytest.mark.parametrize(
    ("name", "factory", "words"),
    [
        ("rip", "PSystemRIPFactory", ["jean canouet"]),
        ("charlie", "PSystemCharlieFactory", ["charlie", "jesuischarlie"]),
        (
            "apple-two",
            "PSystemAppleTwoFactory",
            ["apple //e", "apple ][", "apple II", "Steve Jobs", "Steve Wozniak"],
        ),
    ],
)
def test_easter_eggs_use_java_equals_ignore_case(
    models: ResolvedModels, name: str, factory: str, words: list[str]
) -> None:
    pattern = matcher(models[PREFIX + name], factory)
    rng = random.Random(len(name))
    for _ in range(SAMPLES):
        word = rng.choice(words)
        line = "".join(rng.choice([c, c.upper(), *CASE_ODDITIES]) for c in word)
        expected = any(java_equals_ignore_case(w, line) for w in words)
        assert (pattern.fullmatch(line) is not None) is expected, repr(line)


@pytest.mark.parametrize(
    ("name", "factory", "line", "expected"),
    [
        ("license", "PSystemLicenseFactory", "LiCaNsE \t", True),
        ("license", "PSystemLicenseFactory", " license", False),
        ("license", "PSystemLicenseFactory", "licenſe", False),
        ("license", "PSystemLicenseFactory", "license ", False),
        ("version", "PSystemVersionFactory", "keycheck A1 b2  ", True),
        ("version", "PSystemVersionFactory", "keyimport", True),
        ("version", "PSystemVersionFactory", "authorss", False),
        ("list-fonts", "PSystemListFontsFactory", "LISTFONT  any thing", True),
        ("list-fonts", "PSystemListFontsFactory", "listfonts\tx", False),
        ("list-emoji", "PSystemListEmojiFactory", "emojİ", False),
        ("open-iconic", "PSystemOpenIconicFactory", "openiconic Lock-Locked", True),
        ("open-iconic", "PSystemOpenIconicFactory", "openiconic lock-locked ", False),
        ("colors", "PSystemColorsFactory", "color #Red_1 ", True),
        ("colors", "PSystemColorsFactory", "colors été", False),
        ("sudoku", "PSystemSudokuFactory", "sudoku zz ", True),
        ("dot", "PSystemDotFactory", '  strict digraph "a \\" b" {  ', True),
        ("dot", "PSystemDotFactory", "digraph G {", False),
    ],
)
def test_command_line_examples(
    models: ResolvedModels, name: str, factory: str, line: str, expected: bool
) -> None:
    assert (matcher(models[PREFIX + name], factory).fullmatch(line) is not None) is expected


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("crash when finalizing\ncrash when drawing", True),
        ("crash when finalizing\nx\ncrash when finalizing\ncrash  when drawing", True),
        ("crash when drawing\ncrash when finalizing", False),
        ("crash when finalizing\ncrash when drawing\ncrash when finalizing", False),
        ("x\ncrash when parsing", False),
        ("crash when finalizing\ncrash when parsing\ncrash when drawing", False),
        ("crash\twhen parsing", True),
    ],
)
def test_crash_type_is_the_last_one_selected(
    models: ResolvedModels, body: str, expected: bool
) -> None:
    got = accepts(models, f"@startcrash\n{body}\n@endcrash")
    assert (got["accepted"], got["model"]) == (expected, PREFIX + "crash" if expected else None)


# --- fixtures -------------------------------------------------------------------------


def fixtures(group: str) -> list[Path]:
    return sorted((FIXTURES / group).glob("*.puml"))


def header(path: Path) -> dict[str, str]:
    found = (HEADER.match(line) for line in path.read_text(encoding="utf-8").splitlines())
    return {m["key"]: m["value"] for m in found if m}


def rel(path: Path) -> str:
    return path.relative_to(FIXTURES).as_posix()


def verdict(models: ResolvedModels, path: Path) -> Any:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    return accepts(models, block, raw=True)


@pytest.mark.parametrize("path", fixtures(POS), ids=rel)
def test_pos_fixture_is_accepted(models: ResolvedModels, path: Path) -> None:
    got = verdict(models, path)
    assert (got["accepted"], got["model"]) == (True, header(path)["single-line"])


@pytest.mark.parametrize("path", fixtures(NEG), ids=rel)
def test_neg_fixture_is_rejected(models: ResolvedModels, path: Path) -> None:
    assert verdict(models, path)["accepted"] is False


def gap_params() -> list[Any]:
    return [
        pytest.param(p, id=rel(p), marks=pytest.mark.xfail(strict=True, reason=header(p)["gap"]))
        for p in fixtures(GAP)
    ]


@pytest.mark.parametrize("path", gap_params())
def test_gap_fixture_is_accepted(models: ResolvedModels, path: Path) -> None:
    assert verdict(models, path)["accepted"] is True


def test_every_family_model_has_pos_and_neg_fixtures() -> None:
    named = {group: {header(p)["single-line"] for p in fixtures(group)} for group in (POS, NEG)}
    wanted = {PREFIX + name for name in (SINGLE_LINE | OTHER).values()}
    assert wanted <= named[POS]
    assert wanted <= named[NEG]


@pytest.mark.corpus
def test_fixture_verdicts_equal_the_oracle() -> None:
    from tools.validate.oracle import oracle_verdicts

    paths = fixtures(POS) + fixtures(NEG) + fixtures(GAP)
    verdicts = oracle_verdicts(paths)
    for path in paths:
        (block,) = verdicts[str(path)]
        assert block["accepted"] is (path.parent.name != NEG), rel(path)


@pytest.mark.corpus
def test_open_iconic_names_are_the_jar_resources(models: ResolvedModels) -> None:
    import zipfile

    from tools.config import require

    with zipfile.ZipFile(require("jar")) as jar:
        names = {
            n.removeprefix("openiconic/").removesuffix(".svg")
            for n in jar.namelist()
            if n.startswith("openiconic/") and n.endswith(".svg")
        }
    pattern = matcher(models[PREFIX + "open-iconic"], "PSystemOpenIconicFactory")
    assert all(pattern.fullmatch(f"openiconic {n}") for n in names)
    near = {n[:-1] for n in names} | {n + "x" for n in names}
    assert not any(pattern.fullmatch(f"openiconic {n}") for n in near - names)
