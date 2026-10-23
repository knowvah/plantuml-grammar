"""Turn a block's text into the line stream upstream's command loop sees.

Mirrors, at 97a5992:

* ``utils/StartUtils.java:51-63`` (``isStartDirective``) and ``:95-121``
  (``isEndDirective``): a start line is ``\\s*[@\\\\]start`` plus at least one more
  character; the command loop stops at the first line starting with ``[@\\\\]end``
  (``command/PSystemCommandFactory.java:129-132``).
* ``core/DiagramType.java:69-92``: the diagram types come from the text after ``start``.
* ``preproc2/ReadFilterQuoteComment.java:45-80``: ``'`` line comments and ``/' ... '/``
  block comments never reach the factories.
* ``preproc/ReadLineReader.java:89-102``: ``BufferedReader.readLine`` ends a line at
  ``\\n``, ``\\r`` or ``\\r\\n``, a leading U+FEFF is dropped and U+2013 becomes ``-``.
  Nothing else touches the text (tabs and trailing blanks survive), so ``Line.text`` is
  what ``SingleLineCommand2(doTrim=false)`` matches (``SingleLineCommand2.java:76-81,
  :93, :102``); see ``tools.interp.rules``.
* ``StringUtils.java:505-530`` (``trin``): lines are trimmed of every char ``<= ' '``.
* ``EmbeddedDiagram.java:257-300`` and ``:77-78``: ``{{`` / ``{{type`` ... ``}}`` groups
  are glued into one multiline unit (``PSystemCommandFactory.java:288-307``).

* ``BlockUmlBuilder.java:100-135`` (``split_blocks``): a file splits into blocks; a start
  line opens a block (discarding any unterminated one, ``:101-104``), the first end line
  closes it (``:126-135``), and text outside blocks is ignored (``:113``).

Known gaps: ``@pause`` / ``@unpause`` / ``!exit`` (``BlockUmlBuilder.java:105-125``) are
not modelled by ``split_blocks``, which also sees comments the preprocessor would remove.
``StringLocated.removeInnerComment`` (``ReadFilterQuoteComment.java:76``) strips inline
``/' ... '/`` from kept lines; it is not reproduced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LINE_BREAKS = re.compile(r"\r\n|\r|\n")
BYTE_ORDER_MARK = "\ufeff"
EN_DASH, HYPHEN = "\u2013", "-"
TRIN_CHARS = "".join(chr(c) for c in range(ord(" ") + 1))
START_WORD = "start"
END_WORD = "end"
DIRECTIVE_MARKS = ("@", "\\")
LINE_COMMENT = "'"
LONG_COMMENT_START = "/'"
LONG_COMMENT_END = "'/"
EMBEDDED_START = "{{"
EMBEDDED_END = "}}"
EMBEDDED_TYPES = frozenset(
    "board creole chronology chen chart ditaa ebnf files gantt json mindmap nwdiag "
    "packetdiag regex salt uml wbs wire yaml".split()
)
START_KEYWORD_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


@dataclass(frozen=True)
class Line:
    """One block line: 1-based number within the block text, raw text, trimmed text."""

    number: int
    text: str
    trimmed: str


@dataclass(frozen=True)
class Block:
    """A block split into its start line, optional keyword, command-loop body, end line."""

    start: Line | None
    keyword: str | None
    body: list[Line]
    end: Line | None = None


def read_line(raw: str) -> str:
    """The text of a line as ``ReadLineReader.readLine`` hands it to the command loop."""
    return raw.removeprefix(BYTE_ORDER_MARK).replace(EN_DASH, HYPHEN)


def trin(text: str) -> str:
    """Upstream ``StringUtils.trin``: strip every leading/trailing char ``<= ' '``."""
    return text.strip(TRIN_CHARS)


def _directive_word(text: str, word: str) -> int | None:
    """Index just past ``[@\\]word`` if ``text`` (after whitespace) starts with it."""
    i = 0
    while i < len(text) and text[i].isspace():
        i += 1
    if i >= len(text) or text[i] not in DIRECTIVE_MARKS:
        return None
    end = i + 1 + len(word)
    return end if text[i + 1 : end] == word else None


def is_start_directive(text: str) -> bool:
    """``StartUtils.isStartDirective`` (``StartUtils.java:51-63``)."""
    end = _directive_word(text, START_WORD)
    return end is not None and end < len(text)


def is_end_directive(text: str) -> bool:
    """``StartUtils.isEndDirective`` (``StartUtils.java:119-121``)."""
    return _directive_word(text, END_WORD) is not None


def start_keyword(text: str) -> str:
    """Lower-cased word after ``@start`` (``uml``, ``mindmap``, ...); ``""`` if none."""
    end = _directive_word(text, START_WORD)
    if end is None:
        return ""
    chars: list[str] = []
    for ch in text[end:].lower():
        if ch not in START_KEYWORD_CHARS:
            break
        chars.append(ch)
    return "".join(chars)


def embedded_type(text: str) -> str | None:
    """``EmbeddedDiagram.getEmbeddedType``: ``{{`` alone is ``uml``, else a known type."""
    stripped = text.strip()
    if not stripped.startswith(EMBEDDED_START):
        return None
    suffix = stripped[len(EMBEDDED_START) :].rstrip()
    if suffix == "":
        return "uml"
    return suffix if suffix in EMBEDDED_TYPES else None


def is_embedded_end(text: str) -> bool:
    """A trimmed line equal to ``}}`` (``PSystemCommandFactory.java:298``)."""
    return text.strip() == EMBEDDED_END


def strip_comments(lines: list[Line]) -> list[Line]:
    """Drop comment lines exactly like ``ReadFilterQuoteComment.readLine`` (:52-77)."""
    kept: list[Line] = []
    in_long = False
    for line in lines:
        trim = line.text.replace("\t", " ").strip()
        if in_long:
            in_long = not trim.endswith(LONG_COMMENT_END)
        elif trim.startswith(LINE_COMMENT):
            continue
        elif trim.startswith(LONG_COMMENT_START):
            if trim.endswith(LONG_COMMENT_END):
                continue
            if LONG_COMMENT_END not in trim:
                in_long = True
                continue
            kept.append(line)
        else:
            kept.append(line)
    return kept


def split_block(block_text: str) -> Block:
    """Split into start line, keyword and the lines the command loop iterates.

    A block without a leading ``@start`` line is treated as body only (the harness may
    hand over bare bodies); ``keyword`` is then ``None``.
    """
    raw = [read_line(t) for t in LINE_BREAKS.split(block_text)]
    lines = [Line(n, t, trin(t)) for n, t in enumerate(raw, start=1)]
    first = next((i for i, ln in enumerate(lines) if ln.trimmed), None)
    start: Line | None = None
    keyword: str | None = None
    rest = lines
    if first is not None and is_start_directive(lines[first].text):
        start = lines[first]
        keyword = start_keyword(start.text)
        rest = lines[first + 1 :]
    body: list[Line] = []
    for line in strip_comments(rest):
        if is_end_directive(line.text):
            return Block(start, keyword, body, line)
        body.append(line)
    return Block(start, keyword, body)


def split_blocks(text: str) -> list[str]:
    """The ``@start...@end`` blocks of a file, as ``BlockUmlBuilder`` finds them."""
    blocks: list[str] = []
    current: list[str] | None = None
    for raw in text.split("\n"):
        line = raw.rstrip("\r")
        if is_start_directive(line):
            current = []
        if current is None:
            continue
        current.append(line)
        if is_end_directive(line):
            blocks.append("\n".join(current))
            current = None
    return blocks
