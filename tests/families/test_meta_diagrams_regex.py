"""`@startregex` (T32, ``model/diagrams/meta-diagrams-regex.yaml``) against a port of upstream.

The jar parses every regex line while commands are matched (PSystemRegex.addBlocLines,
regexdiagram/PSystemRegex.java:131-178 at 97a5992), with an operand stack shared by all
lines. ``port_run`` below ports RegexExpression.parse (RegexExpression.java:45-113),
the implicit concatenation (ReTokenType.java:58-72), ShuntingYard (ShuntingYard.java:
50-100) and the stack evaluation, counting only the stack depth. The corpus test checks
the port against the jar; the unit tests check the model against the port.
"""

from __future__ import annotations

import hashlib
import random
import re
import unicodedata
from collections.abc import Callable
from pathlib import Path

import pytest

from tools.interp import accepts
from tools.interp.compile import compile_part
from tools.interp.source import split_blocks
from tools.model import ResolvedModel, ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve

REPO = Path(__file__).resolve().parents[2]
MODEL_ID = "meta-diagrams-regex"
NUL = "\0"
TRIN = "".join(chr(c) for c in range(0x21))
JAVA_SPACE = " \t\n\x0b\f\r\xa0"
ANCHOR_AFTER_BACKSLASH = set("AZzGbB")
ESCAPABLE = set(".*\\?^$|()[]{}<>")
BRACED_QUANTIFIER = re.compile(r"\{[0-9,]+\}")
LETTERS = {"Lu", "Ll", "Lt", "Lm", "Lo"}
# Token kinds: operands push one tile, UNARY pops one and pushes one, BINARY pops two.
OPERAND, UNARY, CONCAT, ALT, OPEN, CLOSE = "o", "u", "+", "|", "(", ")"
EMPTY_GROUP = "[]"
PIECES = [
    "a",
    "b",
    "é",
    "|",
    "(",
    ")",
    "*",
    "+",
    "?",
    "*?",
    "{2}",
    "{2,}",
    "{,}",
    "{x}",
    "{2}?",
    "{",
    "}",
    "]",
    "[ab]",
    "[]",
    "[^a]",
    "[\\]]",
    "[[:alpha:]]",
    "[[:al",
    "\\d",
    "\\b",
    "\\.",
    "\\0123",
    "\\012",
    "\\u00e9",
    "\\u00e",
    "\\p{L}",
    "\\p{L",
    "\\x{41}",
    "\\P{L}",
    "\\U12",
    "(?:",
    "(?=",
    "(?!",
    "(?<=",
    "(?<!",
    "(?<n>",
    "(?<n1>",
    "(?<>",
    "(?#c)",
    "(?#",
    "^",
    "$",
    ".",
    "(?i)",
    " ",
    "(?:?!",
    "<",
    "-",
    "𝐀",
]
WELL_FORMED = ["a", "ab", "(a)", "(a|b)", "a*", "[ab]", "\\d+", "(?:x)", "(?=y)", "x{2}", "."]
SAMPLES = 700
JAR_SAMPLES = 300


class Fail(Exception):
    """Any exception upstream; ProtectedCommand turns it into an error."""


def java_chars(text: str) -> str:
    """The text as Java chars: an astral code point becomes two surrogate halves."""
    out = []
    for ch in text:
        o = ord(ch)
        if o > 0xFFFF:
            o -= 0x10000
            out += [chr(0xD800 + (o >> 10)), chr(0xDC00 + (o & 0x3FF))]
        else:
            out.append(ch)
    return "".join(out)


class Inspector:
    """CharInspectorImpl over one line (utils/CharInspectorImpl.java:50-79)."""

    def __init__(self, line: str) -> None:
        self.s, self.pos, self.line = line, 0, 0 if line else -1

    def peek(self, ahead: int = 0) -> str:
        if self.line == -1 or self.pos + ahead >= len(self.s):
            return NUL
        return self.s[self.pos + ahead]

    def jump(self, times: int = 1) -> None:
        for _ in range(times):
            if self.line == -1:
                raise Fail("IllegalStateException")
            self.pos += 1
            if self.pos >= len(self.s):
                self.line = -1

    def read_through(self, stop: str) -> bool:
        """Consume chars up to and including ``stop``; False if the text ended first."""
        while self.peek() != NUL:
            ch = self.peek()
            self.jump()
            if ch == stop:
                return True
        return False


def _fixed(it: Inspector, count: int) -> None:
    """readUnicodeOrOctalEscape (RegexExpression.java:336-351)."""
    it.jump()
    for _ in range(count):
        if it.peek() == NUL:
            raise Fail("Unexpected end of data")
        it.jump()


def lex_backslash(it: Inspector) -> list[str]:
    nxt = it.peek(1)
    if nxt in ANCHOR_AFTER_BACKSLASH or nxt in ESCAPABLE:
        it.jump(2)
    elif nxt in "0u":
        _fixed(it, 4 if nxt == "0" else 5)
    elif nxt in "px" and it.peek(2) == "{":
        it.jump()
        if not it.read_through("}"):
            raise Fail("Unexpected end of data")
    else:
        it.jump(2)
    return [OPERAND]


def lex_bracket(it: Inspector) -> list[str]:
    if it.peek(1) == "[" and it.peek(2) == ":":
        it.jump(3)
        it.read_through(":")
        it.jump(2)
        return [OPERAND]
    it.jump()
    content = []
    while it.peek() != NUL:
        ch = it.peek()
        it.jump()
        if ch == "]":
            break
        content.append(ch)
        if ch == "\\":
            content.append(it.peek())
            it.jump()
    return [OPERAND if content else EMPTY_GROUP]


def _named(it: Inspector) -> bool:
    i = 3
    while it.peek(i) != NUL:
        if it.peek(i) == ">":
            return i != 3
        if unicodedata.category(it.peek(i)) not in LETTERS:
            return False
        i += 1
    return False


def _comment(it: Inspector) -> list[str]:
    it.jump(3)
    while it.peek() != ")":
        if it.peek() == NUL:
            raise Fail("Unclosed comment")
        it.jump()
    it.jump()
    return []


def lex_paren(it: Inspector) -> list[str]:
    p1, p2, p3 = it.peek(1), it.peek(2), it.peek(3)
    if p1 == "?" and p2 == "#":
        return _comment(it)
    if p1 == "?" and (p2 in "=!" or (p2 == "<" and p3 in "=!")):
        it.jump(3 if p2 in "=!" else 4)
        return [UNARY, OPEN]
    if p1 == "?" and p2 == "<" and _named(it):
        it.jump(3)
        it.read_through(">")
        return [UNARY, OPEN]
    it.jump()
    for flag in ("?:", "?!"):
        if it.peek() + it.peek(1) == flag:
            it.jump(2)
    return [OPEN]


def lex_quantifier(it: Inspector) -> list[str]:
    first = it.peek()
    it.jump()
    text = first
    if first == "{":
        while it.peek() != NUL:
            text += it.peek()
            it.jump()
            if text.endswith("}"):
                break
    if it.peek() == "?":
        text += "?"
        it.jump()
    if first == "{" and not BRACED_QUANTIFIER.fullmatch(text):
        raise Fail("Bad quantifier")
    return ["q"]


LEXERS: dict[str, Callable[[Inspector], list[str]]] = {
    "\\": lex_backslash, "[": lex_bracket, "(": lex_paren,
    "*": lex_quantifier, "+": lex_quantifier, "?": lex_quantifier, "{": lex_quantifier,
}  # fmt: skip
ONE_CHAR = {"^": OPERAND, "$": OPERAND, "|": ALT, ")": CLOSE, ".": OPERAND}


def tokens(line: str) -> list[str]:
    """RegexExpression.parse; quantifiers are "q", look-arounds and named groups UNARY."""
    it, out = Inspector(java_chars(line)), []
    while (ch := it.peek()) != NUL:
        if ch in LEXERS:
            out += LEXERS[ch](it)
        else:
            out.append(ONE_CHAR.get(ch, OPERAND))
            it.jump()
    return out


def concat_needed(t1: str, t2: str) -> bool:
    return t1 not in (UNARY, ALT, OPEN) and t2 not in (ALT, CLOSE, "q")


def rpn(toks: list[str]) -> list[str]:
    seq: list[str] = []
    for tok in toks:
        if seq and concat_needed(seq[-1], tok):
            seq.append(CONCAT)
        seq.append(tok)
    out: list[str] = []
    ops: list[str] = []
    for tok in seq:
        if tok in (UNARY, CONCAT, OPEN):
            ops.append(tok)
        elif tok == ALT:
            while ops and ops[-1] == CONCAT:
                out.append(ops.pop())
            ops.append(tok)
        elif tok == CLOSE:
            while ops and ops[-1] != OPEN:
                out.append(ops.pop())
            if not ops:
                raise Fail("NoSuchElementException")
            ops.pop()
            if ops and ops[-1] == UNARY:
                out.append(ops.pop())
        else:
            out.append(tok)
    return out + ops[::-1]


def evaluate(out: list[str], depth: int) -> int:
    pops = {CONCAT: 2, ALT: 2, UNARY: 1, "q": 1}
    for tok in out:
        if tok in (OPEN, EMPTY_GROUP):
            raise Fail(f"{tok} in the output queue")
        need = pops.get(tok, 0)
        if depth < need:
            raise Fail("NoSuchElementException")
        depth += 1 - need
    return depth


def line_text(line: str) -> str:
    """LINE of CommandRegexfSingleLine on the trimmed line: after Java `[%s]*`."""
    return line.strip(TRIN).lstrip(JAVA_SPACE)


def port_run(lines: list[str]) -> int | None:
    """Stack depth after the lines, or None when one of them fails."""
    depth = 0
    for line in lines:
        try:
            depth = evaluate(rpn(tokens(line_text(line))), depth)
        except Fail:
            return None
    return depth


def needs_more_tiles(lines: list[str]) -> bool:
    """The documented gap: a lexically fine, balanced line underflows a non-empty stack."""
    depth = 0
    for line in lines:
        try:
            out = rpn(tokens(line_text(line)))
        except Fail:
            return False
        if OPEN in out or EMPTY_GROUP in out:
            return False
        try:
            depth = evaluate(out, depth)
        except Fail:
            return depth >= 1
    return False


# --- fixtures ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def models() -> ResolvedModels:
    return resolve(load_dir(REPO / "model"))


@pytest.fixture(scope="module")
def model(models: ResolvedModels) -> ResolvedModel:
    return models[MODEL_ID]


def random_line(rng: random.Random) -> str:
    if rng.random() < 0.4:
        return "".join(rng.choice(WELL_FORMED) for _ in range(rng.randint(1, 3)))
    return "".join(rng.choice(PIECES) for _ in range(rng.randint(1, 6)))


def random_block(rng: random.Random) -> list[str]:
    lines: list[str] = []
    while len(lines) < rng.randint(1, 3):
        line = random_line(rng)
        if line.strip(TRIN) and not line.endswith("\\"):
            lines.append(line)
    return lines


def block_text(lines: list[str]) -> str:
    return "@startregex\n" + "\n".join(lines) + "\n@endregex\n"


def model_accepts(models: ResolvedModels, lines: list[str]) -> bool:
    (block,) = split_blocks(block_text(lines))
    return bool(accepts(models, block)["accepted"])


# --- the port -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lines", "depth"),
    [
        (["abc"], 1),
        (["(?# c)"], 0),
        (["(())"], 0),
        (["a", "*"], 1),
        (["a", "b", "|"], 1),
        (["a{,,}"], 1),
        (["[\\]"], 1),
        (["a\x00)"], 1),
        (["*"], None),
        (["a|"], None),
        (["a", "|"], None),
        (["a{2}?"], None),
        (["(a"], None),
        (["a)"], None),
        (["a[]"], None),
        (["\\037"], None),
        (["[[:digit:]"], None),
        (["(?<n1>a)"], None),
    ],
)
def test_port_examples(lines: list[str], depth: int | None) -> None:
    assert port_run(lines) == depth


# --- model against port --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        (["a\x00)"], True),
        (["a\x00*"], True),
        (["*\x00a"], False),
        (["[a\x00"], True),
    ],
)
def test_a_nul_char_ends_the_line_between_tokens_and_in_a_set(
    models: ResolvedModels, lines: list[str], expected: bool
) -> None:
    """RegexExpression.java:49-50 stops at NUL; readGroup (:303) ends the set there."""
    assert port_run(lines) is not None if expected else port_run(lines) is None
    assert model_accepts(models, lines) is expected


def test_model_agrees_with_the_port_except_the_documented_gap(models: ResolvedModels) -> None:
    rng = random.Random(32)
    gaps = accepted = 0
    for _ in range(SAMPLES):
        lines = random_block(rng)
        want = port_run(lines) is not None
        got = model_accepts(models, lines)
        accepted += want
        if got != want:
            assert got and needs_more_tiles(lines), lines
            gaps += 1
    assert accepted > SAMPLES // 5
    assert gaps < SAMPLES // 50


def test_emitter_line_is_exactly_the_lexable_lines(model: ResolvedModel) -> None:
    """RX_LINE (the emitters' view) matches the lines RegexExpression lexes, `[]` aside."""
    rng = random.Random(64)
    line_rule = compile_part(model.variables["RX_LINE"])
    for _ in range(SAMPLES):
        line = random_line(rng).replace("𝐀", "x")
        try:
            want = EMPTY_GROUP not in tokens(line_text(line))
        except Fail:
            want = False
        assert (line_rule.fullmatch(line.strip(TRIN)) is not None) is want, line


@pytest.mark.corpus
def test_port_agrees_with_the_jar(tmp_path: Path) -> None:
    from tools.validate.oracle import oracle_verdicts

    rng = random.Random(96)
    blocks = [random_block(rng) for _ in range(JAR_SAMPLES)]
    paths = []
    for lines in blocks:
        text = block_text(lines)
        path = tmp_path / (hashlib.sha1(text.encode()).hexdigest()[:12] + ".puml")
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    verdicts = oracle_verdicts(paths)
    for path, lines in zip(paths, blocks, strict=True):
        (verdict,) = verdicts[str(path)]
        assert bool(verdict["accepted"]) is (port_run(lines) is not None), lines
