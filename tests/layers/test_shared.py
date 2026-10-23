"""L3 shared fragments (``model/shared.yaml``): structure, scopes and equivalence.

Every refined fragment keeps the generated regex as its acceptance definition: the
structured Part must accept exactly what the generated Part accepts. Equivalence is
checked on committed samples (unit) and on 50 corpus lines per fragment (corpus).
"""

from __future__ import annotations

import random
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import regex
import yaml

from tools.config import PIN_SHA, require
from tools.interp.compile import part_to_regex
from tools.model.load import load_dir
from tools.model.resolve import resolve
from tools.validate.corpus import PLANTUML_TS, enumerate_corpora
from tools.validate.oracle import oracle_verdicts

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO / "model"
GENERATED_DIR = MODEL_DIR / "generated"
SHARED_FILE = MODEL_DIR / "shared.yaml"
SHARED_ID = "shared"
FIXTURES = REPO / "tests" / "fixtures" / "shared"
SAMPLES = FIXTURES / "samples"
COLORS_SNAPSHOT = FIXTURES / "named-colors.txt"
COLOR_TABLE = "src/main/java/net/sourceforge/plantuml/klimt/color/ColorTrieNode.java"
REGISTER = re.compile(r'register\("(\w+)"')
HEADER = re.compile(r"^' refines: (?P<key>[\w-]+) \| (?P<fragment>.*)$")
SAMPLE_SIZE = 50
MAX_LINE = 300
MAX_SPAN = 60
SEED = 15
TIMEOUT_S = 2.0
NAME_RULE = re.compile(r"^[A-Z][A-Z0-9_]*$")
UNSCOPED_OK = re.compile(r"^(?:\[[^\]]*\\s[^\]]*\][*+]?|\(\?<?[!=][^)]*\))$")


@dataclass(frozen=True)
class Refinement:
    """A structured Part and the generated Part (by variable or leaf) it refines."""

    structured: dict[str, Any]
    model: str
    name: str
    leaf_regex: str | None = None  # None: ``name`` is a variable of ``model``


def _ref(var: str) -> dict[str, Any]:
    return {"ref": var}


def _opt(var: str) -> dict[str, Any]:
    return {"opt": _ref(var)}


STYLE_ITEM = (
    r"(?:#\w+|dotted|dashed|plain|bold|hidden|norank|single|node|thickness=\d+)"
    r"(?:,#\w+|,dotted|,dashed|,plain|,bold|,hidden|,norank|,single|,node|,thickness=\d+)*"
)
REFINEMENTS: dict[str, Refinement] = {
    "color-spec": Refinement(_ref("COLOR_SPEC"), "gen-shared", "COLOR"),
    "color-gradient": Refinement(
        _opt("COLOR_GRADIENT"), "gen-activity-diagram", "BACKCOLOR", r"(#\w+[-\\|/]?\w+)?"
    ),
    "color-ref": Refinement(_opt("COLOR_REF"), "gen-sequence-diagram", "COLOR", r"(#\w+)?"),
    "tag-list": Refinement(_ref("TAG_LIST"), "gen-shared", "TAGS"),
    "url-link": Refinement(_ref("URL_LINK"), "gen-shared", "URL"),
    "visibility-list": Refinement(_ref("VISIBILITY_LIST"), "gen-shared", "VISIBILITY"),
    "visibility-char": Refinement(
        _opt("VISIBILITY_CHAR"), "gen-class-diagram", "VISIBILITY", r"([-#+~])?"
    ),
    "arrow-style": Refinement(_ref("ARROW_STYLE_SPEC"), "gen-shared", "ARROW_STYLE"),
    "arrow-style-multi": Refinement(
        _ref("ARROW_STYLE_MULTI"),
        "gen-description-diagram",
        "ARROW_STYLE1",
        rf"(?:\[({STYLE_ITEM}(?:(?:;{STYLE_ITEM})*))\])?",
    ),
    "stereotype": Refinement(
        _ref("STEREOTYPE_SPEC"), "gen-class-diagram", "STEREO", r"(\<\<.+?\>\>)"
    ),
    "stereotype-group": Refinement(
        _ref("STEREOTYPE_GROUP"),
        "gen-activity-diagram3",
        "STEREOGROUP",
        "(<<[^<>]+>>(?:[\\s ]*<<[^<>]+>>)*)",
    ),
    "arrow-head-left": Refinement(
        _opt("ARROW_HEAD_LEFT"),
        "gen-class-diagram",
        "ARROW_HEAD1",
        r"(<\|:|<\|\||<\||\|\||<<|<_|\}o\b|\|o\b|0\)|\}\||@|#|\)|\*|\+|\bo\b|0|x|<|\}|\^)?",
    ),
    "arrow-head-right": Refinement(
        _opt("ARROW_HEAD_RIGHT"),
        "gen-class-diagram",
        "ARROW_HEAD2",
        r"(:\|>|\|\|>|\|\||>>|\\\\|//|\|>|\(0|\bo\{|\bo\||\|\{|_>|@|#|\(|\*|\+|\bo\b|0|x|\{|\^|>)?",
    ),
    "arrow-body": Refinement(
        _ref("ARROW_BODY_LINE"), "gen-class-diagram", "ARROW_BODY1", r"([-=.]+)"
    ),
}

EXPECTED_SCOPES: dict[str, set[str]] = {
    "COLOR_NAME": {"support.constant.color"},
    "COLOR_HEX": {"constant.other.color.rgb-value"},
    "COLOR_GRADIENT": {
        "punctuation.definition.color",
        "punctuation.separator.gradient",
        "support.constant.color",
        "constant.other.color.rgb-value",
        "constant.other.color",
    },
    "TAG_LIST": {"punctuation.definition.tag", "entity.name.tag"},
    "URL_LINK": {
        "punctuation.definition.link.begin",
        "punctuation.definition.link.end",
        "punctuation.definition.string.begin",
        "punctuation.definition.string.end",
        "punctuation.definition.tooltip.begin",
        "punctuation.definition.tooltip.end",
        "markup.underline.link",
        "string.quoted.other.tooltip",
        "string.other.link.description",
    },
    "VISIBILITY_LIST": {"storage.modifier.visibility"},
    "VISIBILITY_CHAR": {"storage.modifier.visibility"},
    "STEREOTYPE_GROUP": {
        "punctuation.definition.stereotype.begin",
        "punctuation.definition.stereotype.end",
        "entity.other.attribute-name.stereotype",
    },
    "ARROW_HEAD_LEFT": {"keyword.operator.arrow.head"},
    "ARROW_HEAD_RIGHT": {"keyword.operator.arrow.head"},
    "ARROW_BODY_LINE": {"keyword.operator.arrow.body"},
}


# --- pure helpers ---------------------------------------------------------------


def inline(part: Any, variables: dict[str, Any]) -> Any:
    """Replace ``ref`` by the (already resolved) variable Part, recursively."""
    if isinstance(part, list):
        return [inline(p, variables) for p in part]
    if not isinstance(part, dict):
        return part
    if "ref" in part:
        return variables[part["ref"]]
    return {k: inline(v, variables) for k, v in part.items()}


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


def compiled(part: dict[str, Any]) -> Any:
    return regex.compile(part_to_regex(part))


def _end(m: Any) -> int | None:
    return None if m is None else m.end()


def _full(rx: Any, line: str, i: int, j: int) -> bool:
    return rx.fullmatch(line, i, j, timeout=TIMEOUT_S) is not None


def _span_divergences(gen: Any, struct: Any, line: str, i: int) -> list[tuple[Any, ...]]:
    stop = min(len(line), i + MAX_SPAN)
    return [
        ("full", i, j)
        for j in range(i + 1, stop + 1)
        if _full(gen, line, i, j) != _full(struct, line, i, j)
    ]


def divergences(gen: Any, struct: Any, line: str) -> list[tuple[Any, ...]]:
    """Positions where the two patterns behave differently on ``line``.

    Compares the leftmost-first match end at every start position and full-match
    acceptance of every substring (up to ``MAX_SPAN``) starting where either matches.
    """
    out: list[tuple[Any, ...]] = []
    for i in range(len(line) + 1):
        a = _end(gen.match(line, i, timeout=TIMEOUT_S))
        b = _end(struct.match(line, i, timeout=TIMEOUT_S))
        if a != b:
            out.append(("match", i, a, b))
        if (a or i) != i or (b or i) != i:
            out.extend(_span_divergences(gen, struct, line, i))
    if _full(gen, line, 0, len(line)) != _full(struct, line, 0, len(line)):
        out.append(("line",))
    return out


def find_leaf(part: Any, name: str, rx: str) -> dict[str, Any] | None:
    return next((p for p in leaves(part) if p.get("name") == name and p.get("regex") == rx), None)


def generated_part(ref: Refinement) -> dict[str, Any]:
    doc = yaml.safe_load((GENERATED_DIR / f"{ref.model}.yaml").read_text(encoding="utf-8"))
    if ref.leaf_regex is None:
        part: dict[str, Any] = doc["variables"][ref.name]
        return part
    leaf = find_leaf(doc, ref.name, ref.leaf_regex)
    assert leaf is not None, f"{ref.model} has no {ref.name} leaf {ref.leaf_regex!r}"
    return leaf


def color_names(raw_variables: dict[str, Any]) -> list[str]:
    alternatives = raw_variables["COLOR_NAME"]["seq"][0]["alt"]
    return [a["literal"] for a in alternatives]


def snapshot_names() -> list[str]:
    lines = COLORS_SNAPSHOT.read_text(encoding="utf-8").splitlines()
    return [ln for ln in lines if ln and not ln.startswith("#")]


def fixture_headers(path: Path) -> list[tuple[str, str]]:
    found = (HEADER.match(ln) for ln in path.read_text(encoding="utf-8").splitlines())
    return [(m["key"], m["fragment"]) for m in found if m]


def fixture_body(path: Path) -> list[str]:
    """Diagram lines of a fixture (the ``'`` header comments removed)."""
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith("'")]


def raw_shared() -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(SHARED_FILE.read_text(encoding="utf-8"))
    return doc


# --- fixtures -------------------------------------------------------------------


@pytest.fixture(scope="module")
def variables(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("shared-model")
    shutil.copy(SHARED_FILE, root / SHARED_FILE.name)
    resolved = resolve(load_dir(root))
    return dict(resolved[SHARED_ID].variables)


def _pair(key: str, variables: dict[str, Any]) -> tuple[Any, Any]:
    ref = REFINEMENTS[key]
    return compiled(generated_part(ref)), compiled(inline(ref.structured, variables))


# --- unit tests -----------------------------------------------------------------


def test_divergences_detects_a_non_equivalent_pair():
    gen, struct = compiled({"regex": "a+", "ci": True}), compiled({"regex": "a*b?", "ci": True})

    found = divergences(gen, struct, "ab")

    assert ("match", 0, 1, 2) in found
    assert ("line",) in found


def test_divergences_is_empty_for_a_reordered_but_identical_regex():
    gen = compiled({"regex": "(?:#\\w+)?", "ci": True})
    struct = compiled(
        {"opt": {"seq": [{"literal": "#", "ci": True}, {"regex": "\\w+", "ci": True}]}}
    )

    assert divergences(gen, struct, "x #Red y #") == []


@pytest.mark.parametrize("key", sorted(REFINEMENTS))
def test_refined_source_exists_in_generated_models(key):
    part = generated_part(REFINEMENTS[key])

    assert all(leaf.get("ci") is True for leaf in leaves(part))


@pytest.mark.parametrize("key", sorted(REFINEMENTS))
def test_refinement_is_equivalent_on_committed_samples(key, variables):
    gen, struct = _pair(key, variables)
    lines = (SAMPLES / f"{key}.txt").read_text(encoding="utf-8").splitlines()
    hits = [ln for ln in lines if any(m.group() for m in gen.finditer(ln))]

    assert len(hits) >= 5, f"{key}: sample needs at least 5 matching lines"
    assert {ln: divergences(gen, struct, ln) for ln in lines if divergences(gen, struct, ln)} == {}


def test_every_shared_leaf_is_case_insensitive_like_the_generated_ones():
    raw = raw_shared()["variables"]

    assert [leaf for leaf in leaves(raw) if leaf.get("ci") is not True] == []


def test_every_unscoped_leaf_is_whitespace_or_lookaround():
    unscoped = [leaf for leaf in leaves(raw_shared()["variables"]) if "scope" not in leaf]

    assert [leaf for leaf in unscoped if not UNSCOPED_OK.match(leaf.get("regex", ""))] == []


@pytest.mark.parametrize("name", sorted(EXPECTED_SCOPES))
def test_scopes_of_structured_fragment(name, variables):
    assert scopes_of(variables[name]) == EXPECTED_SCOPES[name]


def test_variable_names_are_upper_snake_and_do_not_collide_with_generated():
    generated = set()
    for path in GENERATED_DIR.glob("*.yaml"):
        generated |= set(yaml.safe_load(path.read_text(encoding="utf-8")).get("variables") or {})
    names = set(raw_shared()["variables"])

    assert sorted(n for n in names if not NAME_RULE.match(n)) == []
    assert sorted(names & generated) == []


def test_model_color_list_matches_committed_snapshot():
    names = color_names(raw_shared()["variables"])

    assert names == snapshot_names()
    assert len(names) == 154
    assert names[:2] == ["AliceBlue", "AntiqueWhite"]


@pytest.mark.parametrize(
    ("name", "text", "accepted"),
    [
        ("COLOR_GRADIENT", "#red|blue", True),
        ("COLOR_GRADIENT", "#FF0000-00FF00", True),
        ("COLOR_GRADIENT", "#a", False),
        ("COLOR_REF", "#a", True),
        ("COLOR_SPEC", "#pink;line:red;line.bold;text:red", True),
        ("COLOR_SPEC", "#back:lightblue;header:white", True),
        ("STEREOTYPE_SPEC", "<< (S,#FF7700) Singleton >>", True),
        ("STEREOTYPE_SPEC", "<<>>", False),
        ("TAG_LIST", "$tag1 $tag2", True),
        ("URL_LINK", "[[http://plantuml.com{tooltip} label]]", True),
        ("ARROW_STYLE_SPEC", "[#red,dashed,thickness=2]", True),
        ("ARROW_STYLE_SPEC", "[#red,wavy]", False),
        ("ARROW_STYLE_MULTI", "[#red,bold;#blue,dotted]", True),
    ],
)
def test_structured_fragment_examples(name, text, accepted, variables):
    assert (compiled(variables[name]).fullmatch(text) is not None) is accepted


def _fixture_paths(kind: str) -> list[Path]:
    return sorted((FIXTURES / kind).glob("*.puml"))


@pytest.mark.parametrize("path", _fixture_paths("pos"), ids=lambda p: p.stem)
def test_pos_fixture_fragments_match_both_forms(path, variables):
    headers = fixture_headers(path)

    assert headers, f"{path.name} declares no ' refines: header"
    body = "\n".join(fixture_body(path))
    for key, fragment in headers:
        gen, struct = _pair(key, variables)
        assert fragment in body
        assert gen.fullmatch(fragment) is not None
        assert struct.fullmatch(fragment) is not None


@pytest.mark.parametrize("path", _fixture_paths("neg"), ids=lambda p: p.stem)
def test_neg_fixture_fragments_match_neither_form(path, variables):
    headers = fixture_headers(path)

    assert headers, f"{path.name} declares no ' refines: header"
    for key, fragment in headers:
        gen, struct = _pair(key, variables)
        assert gen.fullmatch(fragment) is None
        assert struct.fullmatch(fragment) is None


# --- corpus tests ---------------------------------------------------------------


def _corpus_lines() -> list[str]:
    seen: set[str] = set()
    for _, path, _ in enumerate_corpora(corpora=(PLANTUML_TS,)):
        for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if len(ln.strip()) <= MAX_LINE:
                seen.add(ln.strip())
    return sorted(seen)


def _fragments(gen: Any, line: str) -> frozenset[str]:
    return frozenset(m.group().lower() for m in gen.finditer(line) if m.group())


def sample_lines(gen: Any, lines: list[str], rng: random.Random) -> list[str]:
    """``SAMPLE_SIZE`` lines where ``gen`` matches non-empty, most diverse first.

    One line per distinct set of matched fragments is taken before any repeat, so
    rare variants (``[dotted]``, spots, gradients) reach the sample; lines without a
    match top the sample up when there are too few hits.
    """
    by_fragments: dict[frozenset[str], list[str]] = {}
    for ln in lines:
        key = _fragments(gen, ln)
        if key:
            by_fragments.setdefault(key, []).append(ln)
    firsts = [rng.choice(group) for group in by_fragments.values()]
    chosen = rng.sample(firsts, min(SAMPLE_SIZE, len(firsts)))
    rest = [ln for ln in lines if ln not in set(chosen)]
    return chosen + rng.sample(rest, SAMPLE_SIZE - len(chosen))


@pytest.fixture(scope="module")
def corpus_lines() -> list[str]:
    return _corpus_lines()


@pytest.mark.corpus
@pytest.mark.parametrize("key", sorted(REFINEMENTS))
def test_refinement_is_equivalent_on_corpus_sample(key, variables, corpus_lines):
    gen, struct = _pair(key, variables)
    sample = sample_lines(gen, corpus_lines, random.Random(f"{SEED}-{key}"))

    assert len(sample) == SAMPLE_SIZE
    assert {ln: divergences(gen, struct, ln) for ln in sample if divergences(gen, struct, ln)} == {}


@pytest.mark.corpus
def test_model_color_list_matches_upstream_color_table():
    src = require("src")
    out = subprocess.run(
        ["git", "-C", str(src), "show", f"{PIN_SHA}:{COLOR_TABLE}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert color_names(raw_shared()["variables"]) == REGISTER.findall(out)


@pytest.mark.corpus
def test_fixture_verdicts_match_the_oracle(tmp_path):
    pos, neg = _fixture_paths("pos"), _fixture_paths("neg")
    verdicts = oracle_verdicts(pos + neg, cache_dir=tmp_path)

    assert {p.name: [b["accepted"] for b in verdicts[str(p)]] for p in pos} == {
        p.name: [True] for p in pos
    }
    assert {p.name: [b["accepted"] for b in verdicts[str(p)]] for p in neg} == {
        p.name: [False] for p in neg
    }
