"""`@startebnf` (T32, ``model/diagrams/meta-diagrams-ebnf.yaml``) against a port of upstream.

The jar tokenizes every EBNF rule while commands are matched (PSystemEbnf.addBlocLines,
ebnf/PSystemEbnf.java:74-83 at 97a5992). ``parses`` below ports the EbnfExpression
constructor (EbnfExpression.java:69-129) over CharInspectorImpl (utils/
CharInspectorImpl.java:50-79): trimmed lines concatenated without a separator, empty
lines skipped. The corpus test checks the port against the jar; the unit tests check
the model against the port, for single-line rules (CommandEBnfSingleLine, with Java's
greedy split of the line) and multiline rules (up to the first line ending in `;`).
"""

from __future__ import annotations

import hashlib
import random
import time
import unicodedata
from pathlib import Path

import pytest
import regex

from tools.interp import accepts
from tools.interp.source import split_blocks
from tools.model import ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve

REPO = Path(__file__).resolve().parents[2]
NUL = "\0"
TRIN = "".join(chr(c) for c in range(0x21))
JAVA_WS = set("\t\n\x0b\x0c\r\x1c\x1d\x1e\x1f")
NOT_JAVA_WS = {"\xa0", " ", " "}
LETTER_OR_DIGIT = {"Lu", "Ll", "Lt", "Lm", "Lo", "Nd"}
SEPARATORS = {"Zs", "Zl", "Zp"}
ONE_TOKEN = set("-*,|=()[]{")
QUOTES = set("\"'?")
# CommandEBnfSingleLine (CommandEBnfSingleLine.java:60-86); `%s` is Java's ASCII `\s` + NBSP.
SPACE = r"[\t\n\x0b\f\r \xa0]"
COMMENT = rf"(?:{SPACE}*\(\*(?:.*[^\t\n\x0b\f\r \xa0].*)\*\){SPACE}*)?"
SINGLE_LINE = regex.compile(
    rf"{COMMENT}(?P<id>[\p{{L}}\p{{N}}_][-\p{{L}}\p{{N}}_]*){COMMENT}{SPACE}*={SPACE}*(?P<line>.*;)",
    regex.IGNORECASE,
)
# UBrexCommandEbnfMultilines start (UBrexCommandEbnfMultilines.java:61-72): `〴an` is
# Character.isLetterOrDigit per UTF-16 char (com/plantuml/ubrex/CharClassRaw.java:71-76).
MULTI_START = regex.compile(r"[\p{L}\p{Nd}_][-\p{L}\p{Nd}_]* *=")
IDS = ["a", "rule", "x_1", "é", "a-b", "a²", "𝐀b", "R2"]
PIECES = [
    " ",
    "b",
    "c1",
    "é",
    "-",
    "*",
    ",",
    "|",
    "=",
    "(",
    ")",
    "[",
    "]",
    "{",
    "}",
    "}-",
    '"x"',
    "'y'",
    "? z ?",
    '"',
    "'",
    "?",
    "(* c *)",
    "(*",
    "*)",
    ";",
    ".",
    "+",
    ":",
    "#",
    "²",
    "𝐀",
    "\t",
    " ",
    "\xa0",
    "<",
    "!",
    "~",
    "&",
    "_",
    '";"',
    "(* ; *)",
]
PREFIXES = ["", "(* c *) ", "(* a *) b *) "]
SAMPLES = 600


class Fail(Exception):
    """An exception upstream; ProtectedCommand turns it into an error."""


def java_chars(text: str) -> str:
    out = []
    for ch in text:
        o = ord(ch)
        if o > 0xFFFF:
            o -= 0x10000
            out += [chr(0xD800 + (o >> 10)), chr(0xDC00 + (o & 0x3FF))]
        else:
            out.append(ch)
    return "".join(out)


def java_ws(ch: str) -> bool:
    """Character.isWhitespace."""
    return ch in JAVA_WS or (unicodedata.category(ch) in SEPARATORS and ch not in NOT_JAVA_WS)


def letter_or_digit(ch: str) -> bool:
    """EbnfExpression.isLetterOrDigit (EbnfExpression.java:266-268)."""
    return ch in "-_" or unicodedata.category(ch) in LETTER_OR_DIGIT


class Inspector:
    """CharInspectorImpl without inserted newlines."""

    def __init__(self, lines: list[str]) -> None:
        self.lines = [java_chars(line.strip(TRIN)) for line in lines]
        self.line, self.pos = 0, 0

    def peek(self, ahead: int = 0) -> str:
        if self.line == -1:
            return NUL
        cur = self.lines[self.line]
        return NUL if self.pos + ahead >= len(cur) else cur[self.pos + ahead]

    def jump(self) -> None:
        if self.line == -1:
            raise Fail("IllegalStateException")
        self.pos += 1
        if self.pos >= len(self.lines[self.line]):
            self.line, self.pos = self.line + 1, 0
        while self.line < len(self.lines) and not self.lines[self.line]:
            self.line += 1
        if self.line >= len(self.lines):
            self.line = -1


def read_comment(it: Inspector) -> str:
    """readComment (EbnfExpression.java:248-264): up to `*)` or the end."""
    it.jump()
    it.jump()
    out = []
    while (ch := it.peek()) != NUL:
        if ch == "*" and it.peek(1) == ")":
            it.jump()
            it.jump()
            break
        out.append(ch)
        it.jump()
    return "".join(out)


def one_char(it: Inspector, ch: str) -> int | None:
    """Tokens one main-loop char adds; None clears the expression (:122-124)."""
    if java_ws(ch):
        return 0
    if ch in ONE_TOKEN or ch == "}":
        if ch == "}" and it.peek(1) == "-":
            it.jump()
        return 1
    if ch in QUOTES:
        it.jump()
        while it.peek() != ch:
            it.jump()
        return 1
    return None


def parses(lines: list[str]) -> bool:
    """EbnfExpression is non-empty and nothing throws."""
    it, count = Inspector(lines), 0
    try:
        while (ch := it.peek()) not in (";", NUL):
            if letter_or_digit(ch) and ch != "-":
                while letter_or_digit(it.peek()):
                    it.jump()
                count += 1
                continue
            if ch == "(" and it.peek(1) == "*":
                count += 1 if read_comment(it).strip(TRIN) else 0
                continue
            added = one_char(it, ch)
            if added is None:
                return False
            count += added
            it.jump()
    except Fail:
        return False
    return count > 0


def single_line_parses(line: str) -> bool | None:
    """None when CommandEBnfSingleLine does not match; else its executeArg verdict."""
    found = SINGLE_LINE.fullmatch(line.strip(TRIN))
    if found is None:
        return None
    return parses([f"{found['id']}={found['line']}"])


def starts_multiline(line: str) -> bool:
    found = MULTI_START.match(line.strip(TRIN))
    return found is not None and all(ord(c) <= 0xFFFF for c in found.group(0))


# --- fixtures ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def models() -> ResolvedModels:
    return resolve(load_dir(REPO / "model"))


def body(rng: random.Random, size: int) -> str:
    text = "".join(rng.choice(PIECES) for _ in range(rng.randint(0, size)))
    return "b" + text if text.lstrip(TRIN).startswith("'") else text


def random_single(rng: random.Random) -> list[str]:
    mid = rng.choice(["", " (* d *)"])
    return [f"{rng.choice(PREFIXES)}{rng.choice(IDS)}{mid} = {body(rng, 6)};"]


def random_multi(rng: random.Random) -> list[str]:
    lines = [f"{rng.choice(IDS)} = {body(rng, 4)}".rstrip(";" + TRIN)]
    lines += [body(rng, 4).rstrip(";" + TRIN) for _ in range(rng.randint(0, 2))]
    return [*lines, body(rng, 4) + ";"]


def expected(lines: list[str]) -> bool | None:
    """Port verdict of a one-rule block; None when the block is not a rule."""
    if len(lines) == 1:
        return single_line_parses(lines[0])
    if single_line_parses(lines[0]) is not None:
        return None
    return parses(lines) if starts_multiline(lines[0]) else False


def block_text(lines: list[str]) -> str:
    return "@startebnf\n" + "\n".join(lines) + "\n@endebnf\n"


def model_accepts(models: ResolvedModels, lines: list[str]) -> bool:
    (block,) = split_blocks(block_text(lines))
    return bool(accepts(models, block)["accepted"])


def random_rules(seed: int, count: int) -> list[tuple[list[str], bool]]:
    rng, out = random.Random(seed), []
    while len(out) < count:
        lines = random_single(rng) if len(out) % 2 else random_multi(rng)
        want = expected(lines)
        if want is not None:
            out.append((lines, want))
    return out


# --- the port -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lines", "ok"),
    [
        (["a=b;"], True),
        (['a="x;y";'], True),
        (["a=b;.;"], True),
        (["a=(* x ;"], True),
        (["a = ( b | c ) , [ d ] , { e }- , - f * 3 ;"], True),
        (["a=b.c;"], False),
        (['a="x;'], False),
        (["a=? x ;"], False),
        (["a²=b;"], False),
        (["a=(* x; *) . ;"], False),
        (["a =", "b . c", ";"], False),
        (["a =", "b | c", ";"], True),
        (['a = "x', ';" ;'], True),
        (["a = (", "* b ) ;"], True),
    ],
)
def test_port_examples(lines: list[str], ok: bool) -> None:
    assert parses(lines) is ok


def test_java_split_decides_which_text_is_tokenized() -> None:
    """Greedy COMMENTA takes `c *) a = b ; ` so `y . ;` is tokenized, not `b ; ...`."""
    assert single_line_parses("(* c *) a = b ; *) x = y . ;") is False
    assert single_line_parses("(* c *) a = b ; *) x = y ;") is True


# --- model against port --------------------------------------------------------------------


def test_model_agrees_with_the_port(models: ResolvedModels) -> None:
    rules = random_rules(32, SAMPLES)
    for lines, want in rules:
        assert model_accepts(models, lines) is want, lines
    assert SAMPLES // 5 < sum(want for _, want in rules) < SAMPLES * 4 // 5


def test_long_multiline_rule_is_fast(models: ResolvedModels) -> None:
    """The join's partial-match early exit keeps a 300-line rule linear (tools/interp/scan.py)."""
    lines = ["a = b", *(f'  | "x{i}" , y{i}' for i in range(300)), "  ;"]
    start = time.process_time()
    assert model_accepts(models, lines) is True
    assert model_accepts(models, [*lines[:-1], "  . ;"]) is False
    assert time.process_time() - start < 5.0


@pytest.mark.corpus
def test_port_agrees_with_the_jar(tmp_path: Path) -> None:
    from tools.validate.oracle import oracle_verdicts

    rules = random_rules(64, SAMPLES // 2)
    paths = []
    for lines, _ in rules:
        text = block_text(lines)
        path = tmp_path / (hashlib.sha1(text.encode()).hexdigest()[:12] + ".puml")
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    verdicts = oracle_verdicts(paths)
    for path, (lines, want) in zip(paths, rules, strict=True):
        (verdict,) = verdicts[str(path)]
        assert bool(verdict["accepted"]) is want, lines
