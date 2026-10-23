"""Salt wireframes (T28, ``model/diagrams/salt.yaml``).

``salt`` extends ``gen-psystem-salt`` and ``common``. ``main`` is the "no data yet" state
(``PSystemSalt.size() == 0``): two head entries, then the generated list, whose
CommandAnything ``set``s ``salt_data``. CommandAnything's parts are the line as
``DataSourceImpl`` tokenizes it (SALT_ROW); the widgets are parsed only when the diagram is
drawn, so the row must match exactly the lines upstream's ``^(.*)$`` matches.

Fixtures (``tests/fixtures/salt``), each with a header before ``@start``::

    ' salt: RuleA, RuleB      rule ids the fixture exercises
    ' gap: <reason>           gap/ only: why the model cannot reproduce the jar

``pos/`` is accepted by the jar as SALT, ``neg/`` and ``gap/`` are rejected by the jar
(``corpus`` test). The interpreter runs each fixture raw with full dispatch (``@startsalt``
reaches only PSystemSaltFactory; the ``@startuml`` fixtures need the uml factories).
"""

from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Any

import pytest

from tools.interp import accepts
from tools.interp.compile import compile_part
from tools.interp.source import split_blocks, trin
from tools.model import Model, ResolvedModel, ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve, top_models

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO / "model"
FIXTURES = REPO / "tests" / "fixtures" / "salt"
POS, NEG, GAP = "pos", "neg", "gap"
SALT_ID, GENERATED_ID, COMMON_ID = "salt", "gen-psystem-salt", "common"
FACTORY, DIAGRAM = "PSystemSaltFactory", "SALT"
MAIN, DATA, ABANDONED = "main", "salt_data", "salt_skinparam_abandoned"
SKINPARAM_BODY = "skinparam_body"
ANYTHING = "CommandAnything"
HEAD = ["SaltNotNeeded", "SaltEmptyDataLine"]
INCONSISTENT, ABANDONED_LINE = "SaltSkinParamBodyInconsistent", "SaltSkinParamAbandonedLine"
SALT_RULES = {ANYTHING, *HEAD, INCONSISTENT, ABANDONED_LINE}
UPSTREAM_PREFIX = "src/main/java/net/sourceforge/plantuml/"
HEADER = re.compile(r"^' (?P<key>salt|gap): (?P<value>.+)$")
NEWLINE_MARK = ""  # jaws/Jaws.java:47, BLOCK_E1_NEWLINE
# Java line terminators that `.` refuses and `$` accepts before the end (no UNIX_LINES).
JAVA_TERMINATORS = "\x85  "
# DataSourceImpl.java:48, compiled by Pattern2 (case-insensitive).
BLOCK_START = re.compile(r"\{(?:[-+^#!*/]|S-|SI|S)?", re.IGNORECASE)
JAVA_WORD = re.compile(r"[A-Za-z0-9_]+")
TOKEN_STARTS = ["", "[", "[X]", "[]", "[ ]", "[[", "(", "(X)", "()", "( )", "^", '"', "<<", "<<x"]
TOKEN_STARTS += ["--", "==", "~~", "..", "+", "++", "T", "N="]
TOKEN_ENDS = ["", "]", "^", '"', ">>", "--", "==", "~~", "..", "#", "-"]
TOKEN_CHARS = '[]()^"<>&*+-=.~XTNSE_ ab0#!:'
ROW_PIECES = ["|", "}", "{", "{+", "{#", "{S", "{si", "{*", "{/", "\\|", "\\{", "\\}", " ", "\t"]
SAMPLES = 1500
TIMEOUT_S = 2.0


@pytest.fixture(scope="module")
def raw_models() -> dict[str, Model]:
    return load_dir(MODEL_DIR)


@pytest.fixture(scope="module")
def models(raw_models: dict[str, Model]) -> ResolvedModels:
    return resolve(raw_models)


@pytest.fixture(scope="module")
def salt(models: ResolvedModels) -> ResolvedModel:
    return models[SALT_ID]


def commands(entries: list[dict[str, Any]]) -> list[str]:
    return [e["command"] for e in entries]


def entry(model: ResolvedModel, context: str, command: str) -> dict[str, Any]:
    (found,) = [e for e in model.contexts[context] if e["command"] == command]
    return found


def variable(salt: ResolvedModel, name: str) -> Any:
    return compile_part(salt.variables[name])


def full(salt: ResolvedModel, name: str, text: str) -> bool:
    return variable(salt, name).fullmatch(text, timeout=TIMEOUT_S) is not None


# --- the model ------------------------------------------------------------------------


def test_salt_is_the_top_model_of_its_factory(
    raw_models: dict[str, Model], models: ResolvedModels
) -> None:
    raw = raw_models[SALT_ID]
    assert (raw.layer, raw.diagram, raw.factory) == ("diagram", DIAGRAM, FACTORY)
    assert raw.include == [GENERATED_ID, COMMON_ID]
    assert top_models(models)[FACTORY] == SALT_ID


def test_main_is_the_head_entries_then_the_data_context(salt: ResolvedModel) -> None:
    got = salt.contexts[MAIN]
    assert commands(got[: len(HEAD)]) == HEAD
    assert commands(got[len(HEAD) :]) == commands(salt.contexts[DATA])
    not_needed, empty_line = got[: len(HEAD)]
    assert (not_needed["reject"], not_needed["parts"]["literal"]) == (True, "salt")
    assert (empty_line["trim"], empty_line["emit"]) == (False, False)
    assert not {"set", "push", "reject"} & set(empty_line)


def test_data_context_keeps_the_generated_order(
    salt: ResolvedModel, models: ResolvedModels
) -> None:
    got = commands(salt.contexts[DATA])
    wanted = commands(models[GENERATED_ID].contexts[MAIN])
    assert [c for c in got if c in set(wanted)] == wanted
    assert got[-1] == ANYTHING
    assert not set(HEAD) & set(got)


@pytest.mark.parametrize("context", [MAIN, DATA])
def test_anything_stores_the_row_and_enters_the_data_state(
    salt: ResolvedModel, context: str
) -> None:
    got = entry(salt, context, ANYTHING)
    assert (got["kind"], got["trim"], got["set"], got["refined_by"]) == (
        "single",
        False,
        DATA,
        SALT_ID,
    )
    assert got["parts"] == salt.variables["SALT_ROW"]
    assert got["provenance"]["file"].endswith("salt/CommandAnything.java")


def test_inconsistent_skinparam_line_abandons_the_bracket(salt: ResolvedModel) -> None:
    body = salt.contexts[SKINPARAM_BODY]
    assert commands(body)[-2:] == ["CommandSkinParamBodySetting", INCONSISTENT]
    assert (body[-1]["set"], body[-1]["emit"]) == (ABANDONED, False)
    assert commands(salt.contexts[ABANDONED]) == [ABANDONED_LINE]
    assert salt.contexts[ABANDONED][0]["emit"] is False
    assert not {"pop", "push", "set"} & set(salt.contexts[ABANDONED][0])


@pytest.mark.parametrize("line", ["salt", NEWLINE_MARK, NEWLINE_MARK * 3])
def test_head_lines_reach_no_other_command(salt: ResolvedModel, line: str) -> None:
    """A head entry runs before the generated list: no earlier upstream command may take it."""
    for found in salt.contexts[DATA]:
        if found["command"] == ANYTHING:
            break
        assert compile_part(found["parts"]).fullmatch(line) is None, found["command"]


def test_hand_written_entries_cite_upstream_file_and_line(raw_models: dict[str, Model]) -> None:
    raw = raw_models[SALT_ID]
    entries = [e for ctx in raw.contexts.values() for e in ctx if "command" in e]
    entries += [e for es in raw.insert_after.values() for e in es]
    entries.append(raw.overrides[ANYTHING])
    for found in entries:
        prov = found["provenance"]
        assert prov["file"].startswith(UPSTREAM_PREFIX), prov
        assert isinstance(prov["line"], int), prov
        assert all(c.startswith(UPSTREAM_PREFIX) for c in prov.get("also", [])), prov


def test_context_entries_do_not_cite_a_patched_class(raw_models: dict[str, Model]) -> None:
    raw = raw_models[SALT_ID]
    patched = set(raw.overrides) | set(raw.insert_after)
    for ctx in raw.contexts.values():
        for found in ctx:
            if "command" in found:
                assert found["provenance"]["class"].rsplit(".", 1)[-1] not in patched


# --- the row: what CommandAnything matches --------------------------------------------


def java_line_matches(line: str) -> bool:
    """``^(.*)$`` with find(): a Java line terminator is allowed only as the last char."""
    return not any(ch in JAVA_TERMINATORS for ch in line[:-1])


def random_line(rng: random.Random) -> str:
    pieces = [rng.choice(ROW_PIECES) if rng.random() < 0.4 else random_token(rng) for _ in range(6)]
    if rng.random() < 0.2:
        pieces.insert(rng.randrange(len(pieces) + 1), rng.choice(JAVA_TERMINATORS))
    return "".join(pieces)


def test_row_matches_exactly_the_lines_java_matches(salt: ResolvedModel) -> None:
    rng = random.Random(28)
    row = variable(salt, "SALT_ROW")
    for _ in range(SAMPLES):
        line = random_line(rng)
        assert (row.fullmatch(line, timeout=TIMEOUT_S) is not None) is java_line_matches(line), line


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("", True),
        ("   ", True),
        ("{T# | a | }", True),
        ("a\\|b \\{ c \\}", True),
        ("trailing \\", True),
        ("ab ", True),
        ("\x85", True),
        ("a b", False),
        ("a\x85b", False),
        ("  x", False),
    ],
)
def test_row_examples(salt: ResolvedModel, line: str, expected: bool) -> None:
    assert full(salt, "SALT_ROW", line) is expected


def test_block_starts_tokenize_like_data_source(salt: ResolvedModel) -> None:
    delimiter = variable(salt, "SALT_DELIMITER")
    for first in "SsIi-+^#!*/T ax":
        for second in "SsIi-+^#!*/T ax":
            text = "{" + first + second
            got = delimiter.match(text)
            assert got is not None and got.end() == BLOCK_START.match(text).end(), text


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("SALT_OPEN_MENU", "{*"),
        ("SALT_OPEN_TAB", "{/"),
        ("SALT_OPEN_SCROLL", "{SI"),
        ("SALT_OPEN_SCROLL", "{s-"),
        ("SALT_OPEN_GRID", "{"),
        ("SALT_OPEN_GRID", "{^"),
        ("SALT_CLOSE", "}"),
        ("SALT_SEPARATOR", "|"),
    ],
)
def test_delimiter_kinds(salt: ResolvedModel, name: str, text: str) -> None:
    assert full(salt, name, text)


# --- cells: one variable per element factory's ready() --------------------------------


def random_token(rng: random.Random) -> str:
    middle = "".join(rng.choice(TOKEN_CHARS) for _ in range(rng.randrange(4)))
    return trin(rng.choice(TOKEN_STARTS) + middle + rng.choice(TOKEN_ENDS))


def is_line(t: str) -> bool:  # ElementFactoryLine.java:60-80
    return any(t.startswith(c * 2) and t.endswith(c * 2) for c in "-=~.")


def is_button(t: str) -> bool:  # ElementFactoryButton.java:67-82
    return not t.startswith("[[") and t.startswith("[") and t.endswith("]")


def is_tree_marker(t: str) -> bool:  # ElementFactoryTree.java:127-136, TableStrategy.java:39-40
    return t == "T" or (len(t) == 2 and t[0] == "T" and t[1] in " +^-!#")


READY = {
    "SALT_LINE": is_line,
    "SALT_TEXT_FIELD": lambda t: t.startswith('"') and t.endswith('"'),
    "SALT_CHECKBOX_ON": lambda t: t.startswith("[X]"),
    "SALT_CHECKBOX_OFF": lambda t: t.startswith(("[]", "[ ]")),
    "SALT_BUTTON": is_button,
    "SALT_DROPLIST": lambda t: t.startswith("^") and t.endswith("^"),
    "SALT_RADIO_ON": lambda t: t.startswith("(X)"),
    "SALT_RADIO_OFF": lambda t: t.startswith(("()", "( )")),
    "SALT_IMAGE_OPEN": lambda t: (
        t == "<<" or JAVA_WORD.fullmatch(t[2:]) is not None and t.startswith("<<")
    ),
    "SALT_IMAGE_REF": lambda t: (
        t.startswith("<<") and t.endswith(">>") and JAVA_WORD.fullmatch(t[2:-2]) is not None
    ),
    "SALT_TREE_MARKER": is_tree_marker,
    "SALT_TREE_ENTRY": lambda t: t.startswith("+"),
    "SALT_TEXT_RUN": lambda t: len(t) > 0,  # ElementFactoryText.java:70-77
}


@pytest.mark.parametrize("name", sorted(READY))
def test_cell_kind_equals_the_factory_ready_check(salt: ResolvedModel, name: str) -> None:
    rng = random.Random(name)
    kind, ready = variable(salt, name), READY[name]
    hits = 0
    for _ in range(SAMPLES):
        token = random_token(rng)
        if not token:
            continue
        got = kind.fullmatch(token, timeout=TIMEOUT_S) is not None
        assert got is bool(ready(token)), token
        hits += got
    assert hits > 0


@pytest.mark.parametrize(
    ("name", "text", "expected"),
    [
        ("SALT_ICON", "<&person>", True),
        ("SALT_ICON", "<#red&home,scale=2>", True),
        ("SALT_ICON", "<&>", False),
        ("SALT_TEXT", "<&person> Login", True),
        ("SALT_TEXT", "Login", True),
        ("SALT_BORDER_POSITION", "N=", True),
        ("SALT_BORDER_POSITION", "N= x", False),
        ("SALT_SPAN", "*", True),
        ("SALT_IMAGE_CLOSE", ">>", True),
        ("SALT_CELL", "  [OK]  ", True),
        ("SALT_CELL", " \t ", True),
    ],
)
def test_cell_examples(salt: ResolvedModel, name: str, text: str, expected: bool) -> None:
    assert full(salt, name, text) is expected


# --- fixtures -------------------------------------------------------------------------


def fixtures(group: str) -> list[Path]:
    return sorted((FIXTURES / group).glob("*.puml"))


def header(path: Path) -> dict[str, str]:
    found = (HEADER.match(line) for line in path.read_text(encoding="utf-8").splitlines())
    return {m["key"]: m["value"] for m in found if m}


def fixture_commands(path: Path) -> list[str]:
    return [c.strip() for c in header(path)["salt"].split(",")]


def rel(path: Path) -> str:
    return path.relative_to(FIXTURES).as_posix()


def verdict(models: ResolvedModels, path: Path) -> Any:
    (block,) = split_blocks(path.read_text(encoding="utf-8"))
    return accepts(models, block, raw=True)


@pytest.mark.parametrize("path", fixtures(POS), ids=rel)
def test_pos_fixture_is_accepted(models: ResolvedModels, path: Path) -> None:
    got = verdict(models, path)
    assert got["accepted"], got["first_failure"]
    assert (got["diagram"], got["model"]) == (DIAGRAM, SALT_ID)


@pytest.mark.parametrize("path", fixtures(NEG), ids=rel)
def test_neg_fixture_is_rejected(models: ResolvedModels, path: Path) -> None:
    assert verdict(models, path)["accepted"] is False


def gap_params() -> list[Any]:
    return [
        pytest.param(p, id=rel(p), marks=pytest.mark.xfail(strict=True, reason=header(p)["gap"]))
        for p in fixtures(GAP)
    ]


@pytest.mark.parametrize("path", gap_params())
def test_gap_fixture_is_rejected(models: ResolvedModels, path: Path) -> None:
    assert verdict(models, path)["accepted"] is False


def test_every_fixture_names_known_commands(salt: ResolvedModel) -> None:
    known = {e["command"] for ctx in salt.contexts.values() for e in ctx}
    for path in fixtures(POS) + fixtures(NEG) + fixtures(GAP):
        assert set(fixture_commands(path)) <= known, rel(path)


def test_every_salt_rule_has_a_fixture() -> None:
    covered = {c for path in fixtures(POS) + fixtures(NEG) for c in fixture_commands(path)}
    assert covered >= SALT_RULES


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
