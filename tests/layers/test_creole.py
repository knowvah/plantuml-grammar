"""L3 Creole layer (``model/creole.yaml``): constructs, scopes, fixtures, acceptance.

Creole is parsed when a label is drawn (``klimt/creole/legacy/CreoleParser.java:142``),
not when commands are matched, so it is a highlighting/structure layer: the jar
accepts every fixture here, including the malformed ones.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import pytest
import regex
import yaml

from tools.interp.compile import part_to_regex
from tools.model.load import load_dir
from tools.model.resolve import resolve
from tools.validate.oracle import oracle_verdicts

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO / "model"
CREOLE_FILE = MODEL_DIR / "creole.yaml"
SHARED_FILE = MODEL_DIR / "shared.yaml"
CREOLE_ID = "creole"
FIXTURES = REPO / "tests" / "fixtures" / "creole"
HEADER = re.compile(r"^' creole: (?P<var>[A-Z_]+) \| (?P<fragment>.*)$")
GROUPS = ("CREOLE_INLINE", "CREOLE_LINE")
NAME_RULE = re.compile(r"^CREOLE_[A-Z0-9_]+$")
UNSCOPED_OK = re.compile(r"^(?:\[[^\]]*\\s[^\]]*\][*+]?|\(\?<?[!=][^)]*\))$")

# The scope each construct must carry on its content or token (TextMate conventions).
CORE_SCOPE: dict[str, str] = {
    "CREOLE_BOLD": "markup.bold",
    "CREOLE_ITALIC": "markup.italic",
    "CREOLE_UNDERLINE": "markup.underline",
    "CREOLE_STRIKE": "markup.strikethrough",
    "CREOLE_WAVE": "markup.underline.wave",
    "CREOLE_MONOSPACE": "markup.raw.monospace",
    "CREOLE_HTML_BOLD": "markup.bold",
    "CREOLE_HTML_ITALIC": "markup.italic",
    "CREOLE_HTML_PLAIN": "markup.other.plain",
    "CREOLE_HTML_UNDERLINE": "markup.underline",
    "CREOLE_HTML_STRIKE": "markup.strikethrough",
    "CREOLE_HTML_WAVE": "markup.underline.wave",
    "CREOLE_BACK": "markup.other.highlight",
    "CREOLE_SIZE": "constant.numeric.integer",
    "CREOLE_COLOR": "constant.other.color",
    "CREOLE_FONT_ATTRIBUTES": "entity.other.attribute-name",
    "CREOLE_SUP": "markup.other.superscript",
    "CREOLE_SUB": "markup.other.subscript",
    "CREOLE_IMG": "markup.underline.link.image",
    "CREOLE_QRCODE": "string.unquoted.qrcode",
    "CREOLE_OPENICON": "entity.name.icon",
    "CREOLE_EMOJI": "constant.other.emoji",
    "CREOLE_MATH": "markup.raw.math",
    "CREOLE_LATEX": "markup.raw.latex",
    "CREOLE_SPRITE": "entity.name.sprite",
    "CREOLE_SPACE": "constant.numeric.integer",
    "CREOLE_FONT_FAMILY": "entity.name.font",
    "CREOLE_URL": "markup.underline.link",
    "CREOLE_UNICODE": "constant.character.escape.unicode",
    "CREOLE_ENTITY": "constant.character.entity",
    "CREOLE_BACKSLASH_ESCAPE": "constant.character.escape",
    "CREOLE_TILDE_ESCAPE": "constant.character.escape",
    "CREOLE_BLOCK_DELIMITER": "entity.name.tag",
    "CREOLE_TABLE_ROW": "markup.table",
    "CREOLE_TREE": "markup.list.tree",
    "CREOLE_RULE": "meta.separator",
    "CREOLE_LIST_BULLET": "markup.list.unnumbered",
    "CREOLE_LIST_NUMBERED": "markup.list.numbered",
    "CREOLE_HEADING": "markup.heading",
}


def leaves(part: Any) -> list[dict[str, Any]]:
    if isinstance(part, list):
        return [leaf for p in part for leaf in leaves(p)]
    if not isinstance(part, dict):
        return []
    if "regex" in part or "literal" in part:
        return [part]
    return [leaf for v in part.values() for leaf in leaves(v)]


def scopes_of(part: Any) -> set[str]:
    return {leaf["scope"] for leaf in leaves(part) if "scope" in leaf}


def raw_creole() -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(CREOLE_FILE.read_text(encoding="utf-8"))
    return doc


def constructs() -> list[str]:
    raw = raw_creole()["variables"]
    return [alt["ref"] for group in GROUPS for alt in raw[group]["alt"]]


def headers(path: Path) -> list[tuple[str, str]]:
    found = (HEADER.match(ln) for ln in path.read_text(encoding="utf-8").splitlines())
    return [(m["var"], m["fragment"]) for m in found if m]


def body(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(ln for ln in lines if not ln.startswith("'"))


def fixture_paths(kind: str) -> list[Path]:
    return sorted((FIXTURES / kind).glob("*.puml"))


def accepts(part: dict[str, Any], text: str) -> bool:
    return regex.fullmatch(part_to_regex(part), text) is not None


@pytest.fixture(scope="module")
def variables(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("creole-model")
    for path in (SHARED_FILE, CREOLE_FILE):
        shutil.copy(path, root / path.name)
    return dict(resolve(load_dir(root))[CREOLE_ID].variables)


def test_construct_list_is_the_core_scope_table():
    assert sorted(constructs()) == sorted(CORE_SCOPE)


@pytest.mark.parametrize("name", sorted(CORE_SCOPE))
def test_construct_carries_its_core_scope(name, variables):
    assert CORE_SCOPE[name] in scopes_of(variables[name])


def test_every_construct_has_a_pos_fixture():
    covered = {var for path in fixture_paths("pos") for var, _ in headers(path)}

    assert sorted(set(constructs()) - covered) == []


@pytest.mark.parametrize("path", fixture_paths("pos"), ids=lambda p: p.stem)
def test_pos_fixture_fragments_are_matched_by_their_construct(path, variables):
    found = headers(path)

    assert found, f"{path.name} declares no ' creole: header"
    for var, fragment in found:
        assert fragment in body(path)
        assert accepts(variables[var], fragment), f"{var} rejects {fragment!r}"


@pytest.mark.parametrize("path", fixture_paths("malformed"), ids=lambda p: p.stem)
def test_malformed_fixture_documents_its_construct(path):
    assert [var for var, _ in headers(path) if var not in CORE_SCOPE] == []
    assert headers(path)


def test_every_leaf_states_ci_explicitly():
    assert [leaf for leaf in leaves(raw_creole()["variables"]) if "ci" not in leaf] == []


def test_every_unscoped_leaf_is_whitespace_or_lookaround():
    unscoped = [leaf for leaf in leaves(raw_creole()["variables"]) if "scope" not in leaf]

    assert [leaf for leaf in unscoped if not UNSCOPED_OK.match(leaf.get("regex", ""))] == []


def test_variable_names_are_prefixed_and_unique_across_models():
    others: set[str] = set()
    for path in [SHARED_FILE, *sorted((MODEL_DIR / "generated").glob("*.yaml"))]:
        others |= set(yaml.safe_load(path.read_text(encoding="utf-8")).get("variables") or {})
    names = set(raw_creole()["variables"])

    assert sorted(n for n in names if not NAME_RULE.match(n)) == []
    assert sorted(names & others) == []


@pytest.mark.parametrize(
    ("name", "text", "accepted"),
    [
        ("CREOLE_BOLD", "**bold**", True),
        ("CREOLE_BOLD", "**unclosed", False),
        ("CREOLE_MONOSPACE", '""""', True),
        ("CREOLE_HTML_BOLD", "<B>to end of line", True),
        ("CREOLE_HTML_BOLD", "<b>x</b>", True),
        ("CREOLE_HTML_WAVE", "<W>x</W>", False),
        ("CREOLE_HTML_STRIKE", "<Del>x</del>", True),
        ("CREOLE_HTML_UNDERLINE", "<u:#abc>x", False),
        ("CREOLE_HTML_UNDERLINE", "<u:#00ff00>x", True),
        ("CREOLE_COLOR", "<color:#abc>x</color>", True),
        ("CREOLE_COLOR", "<cOLOR:red>x", True),
        ("CREOLE_COLOR", "<COLOR:red>x", False),
        ("CREOLE_SUP", "<sup>2</sup>", True),
        ("CREOLE_SUP", "<SUP>2</SUP>", False),
        ("CREOLE_BACK", "<back:red-blue>x</back>", True),
        ("CREOLE_SPRITE", "<#red$foo{scale=2}>", True),
        ("CREOLE_EMOJI", "<:Smile:>", True),
        ("CREOLE_OPENICON", "<&account-login*2>", True),
        ("CREOLE_UNICODE", "<U+1F600>", True),
        ("CREOLE_UNICODE", "<u+00e9>", False),
        ("CREOLE_ENTITY", "&#233;", True),
        ("CREOLE_BACKSLASH_ESCAPE", "\\n", True),
        ("CREOLE_TILDE_ESCAPE", "~*", True),
        ("CREOLE_RULE", "----", True),
        ("CREOLE_RULE", "-----", False),
        ("CREOLE_RULE", "==Title==", True),
        ("CREOLE_RULE", "..dots..", True),
        ("CREOLE_HEADING", "== Section", True),
        ("CREOLE_LIST_BULLET", "** item **bold** tail", True),
        ("CREOLE_LIST_NUMBERED", "##two", True),
        ("CREOLE_TABLE_ROW", "<#lightblue,#red>|= a |= b |", True),
        ("CREOLE_TABLE_ROW", "| a | b", False),
        ("CREOLE_TREE", "|_ child", True),
        ("CREOLE_BLOCK_DELIMITER", "<latex>", True),
        ("CREOLE_BLOCK_DELIMITER", "<LATEX>", False),
        ("CREOLE_URL", "[[http://plantuml.com label]]", True),
    ],
)
def test_construct_examples(name, text, accepted, variables):
    assert accepts(variables[name], text) is accepted


def test_inline_group_prefers_upstream_registration_order():
    names = [alt["ref"] for alt in raw_creole()["variables"]["CREOLE_INLINE"]["alt"]]

    assert names.index("CREOLE_BOLD") < names.index("CREOLE_HTML_BOLD")
    assert names.index("CREOLE_HTML_STRIKE") < names.index("CREOLE_SIZE")
    assert names.index("CREOLE_SIZE") < names.index("CREOLE_SUP")


@pytest.mark.corpus
def test_oracle_accepts_every_creole_fixture_even_malformed(tmp_path):
    paths = fixture_paths("pos") + fixture_paths("malformed")
    verdicts = oracle_verdicts(paths, cache_dir=tmp_path)

    assert {p.name: [b["accepted"] for b in verdicts[str(p)]] for p in paths} == {
        p.name: [True] for p in paths
    }
