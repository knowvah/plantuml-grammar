"""Translate a model regex (``java.util.regex`` semantics) into a JavaScript ``RegExp`` source.

The JavaScript twin of ``tools.model.java_regex``: the same Java semantics (see that
module's docstring: ASCII ``\\d \\w \\s \\b`` and POSIX classes, ``.`` refusing line
terminators, ``$`` / ``\\Z`` accepting one final terminator, ASCII-only case folding),
but the output is meant for ``new RegExp(source, "u")`` at the ES2018 level, because the
engine is embedded in browsers, VS Code and JetBrains JCEF (Chromium 122). So:

* no regex modifiers: ``(?i)``, ``(?i:...)`` and ``(?-i:...)`` change the case mode of the
  translation, and letters are folded explicitly (``[aA]``); scoped forms become ``(?:``;
* no duplicate group names: a named group is emitted unnamed (``(?:``, or ``(`` when the
  pattern has numeric back references, because Java numbers named groups too);
* no ``i`` flag, so folding never leaves ASCII.

Under ``u`` identity escapes are strict (``\\_``, ``\\"``, ``\\ ``, and ``\\-`` outside a
class are syntax errors), so output uses its own code point writer, ``cp_text_js``.

Unsupported Java syntax raises ``JsRegexError``: nested classes, ``&&``, ``\\h \\v \\R``,
``\\Q..\\E``, flags other than ``i``. Atomic groups, possessive quantifiers and named
back references raise ``JsRegexError("... (T5)")`` for now. PCRE-only constructs
(subroutine calls, conditionals) raise too: expand them before translating.

A back reference translated while case-insensitive mode is on raises ``JsRegexError``
(decision D2): JavaScript can fold a back reference only with the ``i`` flag, which folds
Unicode where Java folds ASCII only, and silently matching case-sensitively would be wrong.
Named back references (T5) must follow the same rule.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from tools.model.java_regex import (
    _GROUP,
    _PROPERTY,
    JavaRegexError,
    _apply_flags,
    _class_atom,
    _class_range,
    _fold,
    _hex_escape,
    _is_ascii_letter,
    _property,
    _set_base,
    _single,
)
from tools.model.java_regex_sets import (
    WORD_RANGES,
    RangeList,
    merge,
)

SYNTAX_CHARS = frozenset("^$\\.*+?()[]{}|/")
SUPPLEMENTARY = "[\\u{10000}-\\u{10FFFF}]"
LINE_TERMINATOR = "(?:\\r\\n|(?<!\\r)\\n|[\\r\\x85\\u2028\\u2029])"
DOT = "[^\\n\\r\\x85\\u2028\\u2029]"
END_ANCHOR = f"(?={LINE_TERMINATOR}?$)"
ABSOLUTE_END = "$"
CASED_LETTER = "LC"
SIMPLE_ESCAPES = {"t": 0x09, "n": 0x0A, "r": 0x0D, "f": 0x0C, "a": 0x07, "e": 0x1B}
QUANTIFIER_CHARS = frozenset("*+?{")
SURROGATES = (0xD800, 0xDFFF)
MAX_LATIN1 = 0xFF
MAX_BMP = 0xFFFF
T5_NOTE = "(T5)"

_REPEAT = re.compile(r"\{\d+(?:,\d*)?\}")
_NUMERIC_BACKREF = re.compile(r"\\[1-9]")
_BACKREF_NAME = re.compile(r"\\k<\w+>")


class JsRegexError(ValueError):
    """A regex using Java syntax this translator does not support."""


def cp_text_js(cp: int, *, in_class: bool = False) -> str:
    """One code point as ES2018 ``u``-mode regex text.

    ASCII alphanumerics stay literal; a backslash goes only before ``^ $ \\ . * + ? ( ) [ ]
    { } | /`` (and ``-`` inside a class, where ``\\-`` is legal and outside it is not).
    Controls, space and non-ASCII use ``\\xHH`` / ``\\uHHHH``; supplementary code points
    and lone surrogates use ``\\u{H...}``.
    """
    char = chr(cp)
    if char.isascii() and char.isalnum():
        return char
    if char in SYNTAX_CHARS or (in_class and char == "-"):
        return "\\" + char
    if char.isascii() and char.isprintable() and char != " ":
        return char
    return _numeric_escape(cp)


def _numeric_escape(cp: int) -> str:
    """``\\xHH``, ``\\uHHHH`` or ``\\u{H...}`` (supplementary code points, lone surrogates)."""
    if cp <= MAX_LATIN1:
        return f"\\x{cp:02x}"
    if cp <= MAX_BMP and not SURROGATES[0] <= cp <= SURROGATES[1]:
        return f"\\u{cp:04x}"
    return f"\\u{{{cp:x}}}"


def ranges_text_js(ranges: Iterable[tuple[int, int]]) -> str:
    """The body of a ``[...]`` class for ``ranges``."""
    parts: list[str] = []
    for lo, hi in merge(ranges):
        if lo == hi:
            parts.append(cp_text_js(lo, in_class=True))
        elif hi == lo + 1:
            parts.append(cp_text_js(lo, in_class=True) + cp_text_js(hi, in_class=True))
        else:
            parts.append(f"{cp_text_js(lo, in_class=True)}-{cp_text_js(hi, in_class=True)}")
    return "".join(parts)


def class_text_js(
    ranges: Iterable[tuple[int, int]], raws: Iterable[str] = (), negated: bool = False
) -> str:
    """A complete ``[...]`` class from ranges plus raw items such as ``\\p{L}``."""
    return "[" + ("^" if negated else "") + ranges_text_js(ranges) + "".join(raws) + "]"


ASCII_WORD_CLASS = class_text_js(WORD_RANGES)
_BMP_BASE = f"(?:(?!{SUPPLEMENTARY})[\\p{{L}}\\p{{Nd}}])"
_BMP_MARK = f"(?:(?!{SUPPLEMENTARY})\\p{{Mn}})"
# ``Pattern.Bound`` (see java_regex.py): a non-spacing mark continues the word of the
# letter or digit before it. JavaScript has variable-length lookbehind, so the Python
# lookarounds carry over unchanged.
_LEFT_WORD = f"(?:(?<={ASCII_WORD_CLASS})|(?<={_BMP_BASE}{_BMP_MARK}+))"
_LEFT_NONWORD = f"(?<!{ASCII_WORD_CLASS})(?<!{_BMP_BASE}{_BMP_MARK}+)"
_RIGHT_WORD = f"(?:(?={ASCII_WORD_CLASS})|(?=\\p{{Mn}})(?<={_BMP_BASE}{_BMP_MARK}*))"
_RIGHT_NONWORD = f"(?!{ASCII_WORD_CLASS})(?:(?!\\p{{Mn}})|(?<!{_BMP_BASE}{_BMP_MARK}*))"
WORD_BOUNDARY = f"(?:{_LEFT_WORD}{_RIGHT_NONWORD}|{_LEFT_NONWORD}{_RIGHT_WORD})"
NOT_WORD_BOUNDARY = f"(?:{_LEFT_WORD}{_RIGHT_WORD}|{_LEFT_NONWORD}{_RIGHT_NONWORD})"


def _fold_letter(char: str) -> str:
    """``[aA]`` for an ASCII letter."""
    return f"[{char.lower()}{char.upper()}]"


def _parse_class(src: str, start: int, ci: bool) -> tuple[str, int]:
    """Translate the class opening at ``src[start] == '['``; returns text and next index."""
    i = start + 1
    negated = src.startswith("^", i)
    i += negated
    all_ranges: RangeList = []
    raws: list[str] = []
    while i < len(src) and src[i] != "]":
        ranges, raw, length = _class_atom(src, i, ci)
        i += length
        first = _single(ranges)
        span = _class_range(src, i, first, ci) if first is not None else None
        if span:
            ranges, i = [span[0]], span[1]
        if raw[1:2].isdigit():
            raise JsRegexError(f"back reference or octal escape {raw} in a class")
        all_ranges.extend(_fold(ranges, ci) if ranges else [])
        raws.append(raw)
    if i >= len(src) or not (all_ranges or any(raws)):
        raise JsRegexError("empty or unclosed character class")
    return class_text_js(all_ranges, raws, negated), i + 1


class _Translator:
    """One pass over the source; ``ci`` is the case mode of the group being read."""

    def __init__(self, src: str, ci: bool) -> None:
        self.src, self.ci, self.i = src, ci, 0
        self.out: list[str] = []
        self.saved: list[bool] = []
        self.quantified = False
        self.keep_numbering = _NUMERIC_BACKREF.search(src) is not None

    def run(self) -> str:
        while self.i < len(self.src):
            char = self.src[self.i]
            was_quantified, self.quantified = self.quantified, False
            if char in QUANTIFIER_CHARS:
                self.quantifier(char, was_quantified)
            elif char == "\\":
                self.escape()
            elif char == "[":
                text, self.i = _parse_class(self.src, self.i, self.ci)
                self.out.append(text)
            elif char == "(":
                self.group()
            else:
                self.plain(char)
        return "".join(self.out)

    def emit(self, text: str, length: int = 1) -> None:
        self.out.append(text)
        self.i += length

    def quantifier(self, char: str, after_quantifier: bool) -> None:
        """``* + ? {n,m}``; a ``?`` after a quantifier is lazy, a ``+`` is possessive."""
        if char == "{":
            found = _REPEAT.match(self.src, self.i)
            if found is None:
                raise JsRegexError("illegal repetition")
            self.emit(found.group(), len(found.group()))
        elif after_quantifier and char == "+":
            raise JsRegexError(f"possessive quantifier {T5_NOTE}")
        else:
            self.emit(char)
        self.quantified = not (after_quantifier and char == "?")

    def plain(self, char: str) -> None:
        if char == ")":
            self.ci = self.saved.pop() if self.saved else self.ci
            self.emit(char)
        elif char == ".":
            self.emit(DOT)
        elif char == "$":
            self.emit(END_ANCHOR)
        elif char in "^|":
            self.emit(char)
        elif self.ci and _is_ascii_letter(char):
            self.emit(_fold_letter(char))
        else:
            self.emit(cp_text_js(ord(char)))

    def group(self) -> None:
        found = _GROUP.match(self.src, self.i)
        if found is None or (found.group() == "(" and self.src.startswith("?", self.i + 1)):
            raise JsRegexError("malformed group")
        length = found.end() - found.start()
        if found.group("flags") is not None:
            self.flag_group(found, length)
        elif found.group("call") is not None:
            call = found.group()
            note = f" {T5_NOTE}" if call.startswith("(?P=") else " (expand it first)"
            raise JsRegexError(f"unsupported group {call}{note}")
        elif found.group("comment") is not None:
            self.i += length
        elif found.group("cond") is not None:
            raise JsRegexError("conditional groups are not supported (expand them first)")
        else:
            self.plain_group(found.group(), length)

    def plain_group(self, text: str, length: int) -> None:
        if text in ("(?>", "(?|"):
            raise JsRegexError(f"unsupported group {text} {T5_NOTE}")
        self.saved.append(self.ci)
        named = text.startswith("(?P<") or (text.startswith("(?<") and text[3] not in "=!")
        if named:
            text = "(" if self.keep_numbering else "(?:"
        self.emit(text, length)

    def flag_group(self, found: re.Match[str], length: int) -> None:
        spec, end = found.group("flags"), found.group("flag_end")
        if end == ")":
            self.ci = _apply_flags(spec, self.ci)
            self.i += length
            return
        self.saved.append(self.ci)
        self.ci = _apply_flags(spec, self.ci)
        self.emit("(?:", length)

    def escape(self) -> None:
        src, i = self.src, self.i
        if i + 1 >= len(src):
            raise JsRegexError("pattern ends with a backslash")
        char = src[i + 1]
        if char in "dDwWsS":
            ranges = _set_base(char) or []
            self.emit(class_text_js(ranges, negated=char.isupper()), 2)
        elif char in "bB":
            self.emit(WORD_BOUNDARY if char == "b" else NOT_WORD_BOUNDARY, 2)
        elif char in "pP":
            self.property_escape()
        elif char in "Zz":
            self.emit(END_ANCHOR if char == "Z" else ABSOLUTE_END, 2)
        else:
            self.other_escape(char)

    def property_escape(self) -> None:
        match = _PROPERTY.match(self.src, self.i)
        if match is None:
            raise JsRegexError("malformed property escape")
        ranges, raw = _property(match, self.ci)
        self.emit(class_text_js(ranges) if ranges is not None else raw, match.end() - self.i)

    def other_escape(self, char: str) -> None:
        src, i = self.src, self.i
        if _BACKREF_NAME.match(src, i):
            raise JsRegexError(f"named back reference {T5_NOTE}")
        if char in "123456789":
            if self.ci:
                raise JsRegexError(f"back reference \\{char} under ci is unsupported (D2)")
            self.emit(src[i : i + 2], 2)
            return
        hexed = _hex_escape(src, i)
        if hexed:
            self.code_point(hexed[0], hexed[1])
        elif char in SIMPLE_ESCAPES:
            self.code_point(SIMPLE_ESCAPES[char], 2)
        elif char.isalnum() and char.isascii():
            raise JsRegexError(f"unsupported escape \\{char}")
        else:
            self.code_point(ord(char), 2)

    def code_point(self, cp: int, length: int) -> None:
        """A single-character escape, folded to a two-case class for ASCII letters under ``ci``."""
        if self.ci and _is_ascii_letter(chr(cp)):
            self.emit(_fold_letter(chr(cp)), length)
        else:
            self.emit(cp_text_js(cp), length)


def to_js(pattern: str, *, ci: bool = False) -> str:
    """JavaScript source (flag ``u``, ES2018) with the semantics Java gives ``pattern``.

    ``ci`` is ``Pattern.CASE_INSENSITIVE`` (ASCII folding) for the whole pattern; inline
    ``(?i:...)`` / ``(?-i:...)`` groups switch it locally. Raises ``JsRegexError`` for Java
    syntax outside the supported subset (see the module docstring).
    """
    try:
        return _Translator(pattern, ci).run()
    except JavaRegexError as error:
        raise JsRegexError(str(error)) from error


def literal_to_js(text: str, *, ci: bool = False) -> str:
    """JavaScript source (flag ``u``) matching ``text`` exactly, folding ASCII case under ``ci``."""
    return "".join(
        _fold_letter(char) if ci and _is_ascii_letter(char) else cp_text_js(ord(char))
        for char in text
    )


def line_pattern_js(body: str) -> str:
    """``body`` as Java's ``^body$`` sees a line: one final terminator may follow it.

    ``^(?:body)LT?$`` for flag ``u``, where ``LT`` is the Java line terminator.
    """
    return f"^(?:{body}){LINE_TERMINATOR}?$"


__all__ = [
    "JsRegexError",
    "cp_text_js",
    "line_pattern_js",
    "literal_to_js",
    "to_js",
]
