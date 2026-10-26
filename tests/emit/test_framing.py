"""Block framing: start keywords from ``start_map`` and any-``@end``.

Upstream closes a block at the first ``StartUtils.isEndDirective`` line (``[@\\\\]end`` plus any
suffix; utils/StartUtils.java:119-121), and offers a factory under every keyword that lists it
(``DiagramType.findStartTypes``, core/DiagramType.java:94-218).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers.models import repo_resolved
from tools.emit import keywords, textmate
from tools.model.load import load_dir
from tools.model.resolve import resolve

FRAMING = Path(__file__).parent / "fixtures" / "framing"
TOY = Path(__file__).parent / "fixtures" / "toy"


@pytest.fixture(scope="module")
def toy_resolved():
    return resolve(load_dir(FRAMING))


@pytest.fixture(scope="module")
def real_resolved():
    return repo_resolved()


# --- keywords ------------------------------------------------------------------------


def test_document_start_map_comes_from_the_document_layer(toy_resolved) -> None:
    assert list(keywords.document_start_map(toy_resolved)) == [
        "uml",
        "sprites",
        "gantt",
        "project",
        "nomodel",
    ]


def test_document_start_map_is_empty_without_a_document_layer() -> None:
    assert keywords.document_start_map(resolve(load_dir(TOY))) == {}


def test_model_is_offered_under_every_keyword_naming_its_factory(toy_resolved) -> None:
    groups = keywords.group_by_keyword(toy_resolved)
    assert {k: [m.id for m in v] for k, v in groups.items()} == {
        "gantt": ["fr_gantt"],
        "project": ["fr_gantt"],
        "uml": ["fr_list"],
        "sprites": ["fr_list"],
    }


def test_models_without_factory_fall_back_to_the_diagram_type_keyword() -> None:
    groups = keywords.group_by_keyword(resolve(load_dir(TOY)))
    assert list(groups) == ["uml", "salt"]


@pytest.mark.parametrize(
    ("diagram", "keyword"),
    [("CLASS", "uml"), ("SPRITES", "uml"), ("SALT", "salt"), ("PACKET", "packetdiag")],
)
def test_start_keyword_by_diagram_type(diagram: str, keyword: str) -> None:
    assert keywords.start_keyword(diagram) == keyword


def test_every_real_start_keyword_has_a_textmate_block(real_resolved) -> None:
    expected = set(keywords.document_start_map(real_resolved))
    assert len(expected) == 29
    assert {"sprites", "project", "uml", "gantt"} <= expected
    grammar = textmate.emit_textmate(real_resolved)
    blocks = [p["begin"] for p in grammar["patterns"] if "begin" in p]
    for keyword in sorted(expected):
        assert f"diagram_{keyword}" in grammar["repository"], keyword
        assert any(b.endswith(f"start(?i:{keyword}))") for b in blocks), keyword
    assert len(blocks) == len(expected) + 1  # one block per keyword, then the unknown-word block


# --- TextMate framing -------------------------------------------------------------------


def test_textmate_block_ends_at_any_end_directive(toy_resolved) -> None:
    grammar = textmate.emit_textmate(toy_resolved)
    blocks = [p for p in grammar["patterns"] if "begin" in p]
    assert {b["end"] for b in blocks} == {r"^\s*([@\\]end[A-Za-z0-9]*)"}
    assert [b["begin"] for b in blocks][3] == r"^\s*([@\\]start(?i:sprites))"
    assert "diagram_project" in grammar["repository"]


# --- start words no keyword covers (PSystemUnsupported) --------------------------------------


def test_uncovered_lookahead_is_in_the_other_start_pattern() -> None:
    assert keywords.uncovered_lookahead(["uml", "mindmap"]) == "(?!(?:mindmap|uml))"
    assert keywords.uncovered_lookahead(["uml", "mindmap"]) in keywords.other_start_pattern(
        ["uml", "mindmap"]
    )


def test_other_start_pattern_excludes_every_keyword_prefix_longest_first() -> None:
    pattern = keywords.other_start_pattern(["uml", "gantt", "mindmap"])
    assert pattern == r"[ \t]*[@\\]start(?!(?:mindmap|gantt|uml))[^\r\n]+"


def test_real_start_keywords_are_prefix_free(real_resolved) -> None:
    # Each START_<KW> is `keyword` + anything, so a key that prefixed another would give one
    # start line two blocks; upstream's getTypes has no such pair either.
    keys = sorted(keywords.document_start_map(real_resolved))
    clashes = [(a, b) for a in keys for b in keys if a != b and b.startswith(a)]
    assert clashes == []


def test_other_start_pattern_lists_each_keyword_once() -> None:
    pattern = keywords.other_start_pattern(["uml", "salt", "uml", "salt"])
    assert pattern == r"[ \t]*[@\\]start(?!(?:salt|uml))[^\r\n]+"
