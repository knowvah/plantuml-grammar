"""Guards (#4): heads of Parts, guard emission, and guarded verdicts equal unguarded ones."""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import regex

from tests.emit.engine_support import (
    JOINER,
    PIN,
    engine_entries,
    entry,
    lit,
    node_verdicts,
    rx,
    synthetic,
)
from tests.model.test_js_subroutines import FIXTURES
from tools.emit import engine as eng
from tools.emit.guard import GUARD_MAX_BYTES, GUARD_MIN_BYTES, guard_head
from tools.interp.compile import compile_part
from tools.interp.source import split_block, split_blocks
from tools.model import Part, ResolvedModels
from tools.model.js_prefix import prefix_pattern
from tools.validate.corpus import enumerate_corpora

BIG = rx("(?:" + "|".join(f"w{i:05d}" for i in range(GUARD_MIN_BYTES // 6)) + ")")
NATIVE_LEAF = "(?(DEFINE)(?<x>a))(?&x)"
MAX_JOINED_LINES = 3


def js(part: Part) -> str:
    return eng.part_to_js(part)


def head(part: Part) -> Part | None:
    return guard_head(part, js, lambda p: p.get("regex") == NATIVE_LEAF)


# --- heads ---------------------------------------------------------------------------------


def test_a_small_part_is_its_own_head():
    part = {"seq": [lit("json"), rx("\\s+")]}
    assert head(part) == part


def test_seq_keeps_the_leading_children_that_fit():
    assert head({"seq": [lit("json"), rx("\\s+"), BIG, lit("x")]}) == {
        "seq": [lit("json"), rx("\\s+")]
    }


def test_seq_cuts_inside_the_child_that_does_not_fit():
    inner = {"seq": [lit("b"), BIG]}
    assert head({"seq": [lit("a"), inner, lit("c")]}) == {"seq": [lit("a"), {"seq": [lit("b")]}]}


def test_alt_takes_every_alternative_head_or_none():
    part = {"alt": [{"seq": [lit("x"), BIG]}, {"seq": [lit("y"), BIG]}]}
    assert head(part) == {"alt": [{"seq": [lit("x")]}, {"seq": [lit("y")]}]}
    assert head({"alt": [{"seq": [lit("x"), BIG]}, BIG]}) is None


def test_plus_uses_the_head_of_its_body_and_opt_or_star_too_big_give_none():
    assert head({"plus": {"seq": [lit("p"), BIG]}}) == {"seq": [lit("p")]}
    assert head({"opt": {"seq": [lit("p"), BIG]}}) is None
    assert head({"star": {"seq": [lit("p"), BIG]}}) is None
    assert head(BIG) is None


def test_a_head_that_matches_the_empty_string_is_dropped():
    assert head({"seq": [{"opt": lit("a")}, BIG]}) is None
    assert head({"seq": [rx("\\s*"), BIG]}) is None


def test_a_native_leaf_never_enters_a_head():
    native = rx(NATIVE_LEAF)
    assert head({"seq": [lit("json "), native, BIG]}) == {"seq": [lit("json ")]}
    assert head({"seq": [native, BIG]}) is None


def test_heads_stay_within_the_budget():
    words = {"seq": [lit(f"k{i:04d}") for i in range(2 * GUARD_MAX_BYTES)]}
    found = head({"seq": [words, BIG]})
    assert found is not None
    assert len(js(found).encode()) <= GUARD_MAX_BYTES


# --- emission -------------------------------------------------------------------------------


def test_a_large_start_pattern_gets_a_start_guard_and_a_small_one_none():
    data = eng.build_engine(
        synthetic([entry({"seq": [lit("json"), BIG]}), entry(lit("small"))]), PIN
    )
    big, small = (data["patterns"][e["start"]] for e in data["context_table"][0])
    assert big["guard"] == "^(?:(?:(?:json)))"
    assert "guard" not in small


def test_a_large_join_prefix_gets_a_prefix_guard():
    part = {"seq": [lit("json"), BIG]}
    data = eng.build_engine(synthetic([entry(part, join={"max_lines": 5})]), PIN)
    prefix = data["patterns"][data["context_table"][0][0]["join"]["prefix"]]
    head_part = {"seq": [lit("json")]}
    assert prefix["guard"] == f"{prefix_pattern(head_part)}|^(?:(?:(?:json)))"


def test_unsupported_patterns_get_no_guard():
    data = eng.build_engine(synthetic([entry({"seq": [lit("j"), rx(r"(a)(?>b)\1"), BIG]})]), PIN)
    assert all("guard" not in p for p in data["patterns"] if "unsupported" in p)


# --- guarded verdicts equal unguarded ones (Node) -------------------------------------------


def body_lines(paths: Iterable[Path]) -> list[list[str]]:
    """Trimmed body lines of every block, one list per block."""
    blocks = []
    for path in paths:
        for block in split_blocks(path.read_text(errors="replace")):
            blocks.append([line.trimmed for line in split_block(block).body])
    return blocks


def joined(lines: list[str]) -> Iterator[str]:
    """What a join prefix sees: one to three consecutive lines, each followed by the joiner."""
    for i in range(len(lines)):
        for n in range(1, MAX_JOINED_LINES + 1):
            if i + n <= len(lines):
                yield "".join(line + JOINER for line in lines[i : i + n])


def guarded_ids(built: dict[str, Any], resolved: ResolvedModels) -> dict[int, tuple[str, Part]]:
    """Guarded pattern ids -> (``start`` or ``prefix``, the Part they were built from)."""
    out: dict[int, tuple[str, Part]] = {}
    for mid, name, index, source in engine_entries(resolved, built):
        emitted = built["context_table"][built["models"][mid]["contexts"][name]][index]
        roles = [("start", emitted["start"], source["parts"])]
        if source.get("end") is not None:
            roles.append(("start", emitted["end"], source["end"]))
        if "join" in emitted:
            roles.append(("prefix", emitted["join"]["prefix"], source["parts"]))
        for role, ident, part in roles:
            if "guard" in built["patterns"][ident]:
                out.setdefault(ident, (role, part))
    return out


@dataclass(frozen=True)
class Engine:
    """The built engine (as data and as a file) and the TS build that runs it."""

    built: dict[str, Any]
    resolved: ResolvedModels
    file: Path
    dist: Path


@pytest.fixture
def engine(built, resolved, engine_file, engine_dist) -> Engine:
    return Engine(built, resolved, engine_file, engine_dist)


def texts_by_role(paths: list[Path]) -> dict[str, list[str]]:
    """Start patterns see single lines; join prefixes see joined windows."""
    blocks = body_lines(paths)
    return {
        "start": sorted({line for block in blocks for line in block}),
        "prefix": sorted({text for block in blocks for text in joined(block)}),
    }


def disagrees(role: str, python: regex.Pattern[str], text: str, verdict: bool) -> bool:
    """A start pattern must give Python's ``fullmatch``. A join prefix must accept whatever
    Python's partial match accepts; like the unguarded prefix (``js_prefix``) it may accept
    more, and with the guard it accepts less of that excess (``tools.emit.guard``)."""
    if role == "start":
        return verdict != (python.fullmatch(text) is not None)
    return not verdict and python.fullmatch(text, partial=True) is not None


def violations(engine: Engine, paths: list[Path]) -> list[str]:
    """Texts where a guarded matcher disagrees with Python."""
    texts = texts_by_role(paths)
    ids = guarded_ids(engine.built, engine.resolved)
    assert ids
    jobs = {str(i): (i, texts[role]) for i, (role, _) in ids.items()}
    node = node_verdicts(engine.file, engine.dist, jobs)
    print({"patterns": len(ids), **{k: len(v) for k, v in texts.items()}}, file=sys.stderr)
    return [
        f"{role} {ident}: {text[:120]!r} node={verdict}"
        for ident, (role, part) in ids.items()
        for python in [compile_part(part)]
        for text, verdict in zip(texts[role], node[str(ident)], strict=True)
        if disagrees(role, python, text, verdict)
    ]


def test_guarded_matchers_agree_with_python_on_fixture_lines(engine):
    assert violations(engine, sorted(FIXTURES.rglob("*.puml"))) == []


@pytest.mark.corpus
def test_guarded_matchers_agree_with_python_on_corpus_lines(engine):
    paths = sorted(FIXTURES.rglob("*.puml")) + [p for _, p, _ in enumerate_corpora()]
    assert violations(engine, paths) == []


def test_every_guard_is_a_plain_whole_line_regex(built):
    for pattern in built["patterns"]:
        if "guard" in pattern:
            assert pattern["guard"].startswith("^")
            assert re.search(r"\\k<_a@", pattern["guard"]) is None
