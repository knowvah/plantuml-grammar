"""Translate a model regex (``java.util.regex`` semantics) into a Python ``regex`` pattern.

Model regexes mean what upstream's Java means. PlantUML compiles every ``Pattern2`` with
``Pattern.CASE_INSENSITIVE`` only (``regex/Pattern2.java:114`` at 97a5992) and no source
under ``src/main/java`` sets ``UNICODE_CASE`` or ``UNICODE_CHARACTER_CLASS``. In Java 21
that means, verified with a jshell-style probe (``Pattern`` docs, "Unicode support"):

* ``.`` refuses ``\\n \\r U+0085 U+2028 U+2029`` (no DOTALL);
* ``\\d \\w \\s \\D \\W \\S`` and the POSIX classes (``\\p{Alpha}``...) are ASCII;
* ``\\b`` is ASCII-word, except that a non-spacing mark after a letter or digit counts as
  a word character (``Pattern.Bound``);
* case-insensitive matching folds ASCII only, in literals, ranges and back references,
  and ``\\p{Lu}``/``\\p{Ll}``/``\\p{Lt}`` become "any cased letter";
* ``$`` and ``\\Z`` also match before one final line terminator;
* ``\\p{L}``, ``\\p{N}``... stay Unicode.

Python's ``regex`` module is Unicode for every one of these, so the interpreter must not
read model regexes directly.
``to_python`` rewrites one regex; ``literal_to_python`` does the same for fixed text;
``line_pattern`` adds the implicit ``$`` that upstream's ``^...$`` wrapper brings.

Constructs outside Java's grammar that models use (``(?(DEFINE)``, ``(?&name)``,
``(?P<n>``, ``(?P=n)``, conditionals) pass through unchanged. Unsupported Java syntax
(nested classes, ``&&``, ``\\h \\v \\R``, flags other than ``i``) raises ``JavaRegexError``.
Known residual gap: a back reference under ``ci`` folds Unicode (``regex``) where Java
folds ASCII only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import regex

from tools.model.java_regex_sets import (
    POSIX_CLASSES,
    SPACE_RANGES,
    WORD_RANGES,
    Range,
    RangeList,
    class_text,
    complement,
    cp_text,
    fold_ascii,
)

DIGIT_RANGES: RangeList = [(0x30, 0x39)]
SUPPLEMENTARY = "[\\U00010000-\\U0010ffff]"
LINE_TERMINATOR = "(?:\\r\\n|(?<!\\r)\\n|[\\r\\x85\\u2028\\u2029])"
DOT = "[^\\n\\r\\x85\\u2028\\u2029]"
END_ANCHOR = f"(?={LINE_TERMINATOR}?\\Z)"
ABSOLUTE_END = "\\Z"
CASED_LETTER = "LC"
CASE_PROPERTIES = frozenset({"Lu", "Ll", "Lt"})
SIMPLE_ESCAPES = {"t": 0x09, "n": 0x0A, "r": 0x0D, "f": 0x0C, "a": 0x07, "e": 0x1B}
HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
ASCII_WORD_CLASS = class_text(WORD_RANGES)

_BMP_BASE = f"(?:(?!{SUPPLEMENTARY})[\\p{{L}}\\p{{Nd}}])"
_BMP_MARK = f"(?:(?!{SUPPLEMENTARY})\\p{{Mn}})"
# ``Pattern.Bound``: a non-spacing mark continues the word of the letter or digit before
# it. Left of the boundary the mark is the previous char; right of it, the next char.
_LEFT_WORD = f"(?:(?<={ASCII_WORD_CLASS})|(?<={_BMP_BASE}{_BMP_MARK}+))"
_LEFT_NONWORD = f"(?<!{ASCII_WORD_CLASS})(?<!{_BMP_BASE}{_BMP_MARK}+)"
_RIGHT_WORD = f"(?:(?={ASCII_WORD_CLASS})|(?=\\p{{Mn}})(?<={_BMP_BASE}{_BMP_MARK}*))"
_RIGHT_NONWORD = f"(?!{ASCII_WORD_CLASS})(?:(?!\\p{{Mn}})|(?<!{_BMP_BASE}{_BMP_MARK}*))"
WORD_BOUNDARY = f"(?:{_LEFT_WORD}{_RIGHT_NONWORD}|{_LEFT_NONWORD}{_RIGHT_WORD})"
NOT_WORD_BOUNDARY = f"(?:{_LEFT_WORD}{_RIGHT_WORD}|{_LEFT_NONWORD}{_RIGHT_NONWORD})"

_GROUP = re.compile(
    r"""\(\?(?:
        (?P<call>(?:P=|P>|&)\w+\)|R\)|[+-]?\d+\))
      | (?P<comment>\#[^)]*\))
      | (?P<cond>\([^)]*\))
      | (?P<plain>[:=!>|]|<[=!]|P?<\w+>)
      | (?P<flags>[a-zA-Z]*(?:-[a-zA-Z]*)?)(?P<flag_end>[:)])
    )|\(""",
    re.VERBOSE,
)
_PROPERTY = re.compile(r"\\([pP])(?:\{([^}]*)\}|(\w))")
_BACKREF_NAME = re.compile(r"\\k<\w+>")


class JavaRegexError(ValueError):
    """A regex using Java syntax this translator does not support."""


@dataclass
class _Class:
    """Accumulated items of one bracket class."""

    ranges: RangeList = field(default_factory=list)
    raws: list[str] = field(default_factory=list)


def _fold(ranges: RangeList, ci: bool) -> RangeList:
    return fold_ascii(ranges) if ci else ranges


def _property(match: re.Match[str], ci: bool) -> tuple[RangeList | None, str]:
    """``(posix ranges or None, raw text)`` of a ``\\p{..}`` / ``\\P{..}`` escape."""
    negated = match.group(1) == "P"
    name = match.group(2) if match.group(2) is not None else match.group(3)
    if name in POSIX_CLASSES:
        ranges = _fold(POSIX_CLASSES[name], ci)
        return (complement(ranges) if negated else ranges), ""
    if ci and name in CASE_PROPERTIES:
        name = CASED_LETTER
    return None, f"\\{match.group(1)}{{{name}}}"


def _set_base(char: str) -> RangeList | None:
    """The ASCII set behind ``\\d \\w \\s`` (either case); ``None`` for other letters."""
    return {"d": DIGIT_RANGES, "w": WORD_RANGES, "s": SPACE_RANGES}.get(char.lower())


def _set_escape(char: str) -> RangeList | None:
    """Ranges of ``\\d \\D \\w \\W \\s \\S``; ``None`` for any other escape letter."""
    base = _set_base(char)
    if base is None:
        return None
    return complement(base) if char.isupper() else list(base)


def _hex_escape(src: str, i: int) -> tuple[int, int] | None:
    """``(code point, length)`` of ``\\xHH`` / ``\\uHHHH`` / ``\\UHHHHHHHH`` at ``i``."""
    digits = {"x": 2, "u": 4, "U": 8}.get(src[i + 1 : i + 2])
    text = src[i + 2 : i + 2 + (digits or 0)]
    if digits and len(text) == digits and all(c in HEX_DIGITS for c in text):
        return int(text, 16), 2 + digits
    return None


def _is_ascii_letter(char: str) -> bool:
    return char.isascii() and char.isalpha()


def _class_escape(src: str, i: int, ci: bool) -> tuple[RangeList | None, str, int]:
    """Translate the escape at ``src[i]`` inside a class: ``(ranges, raw, length)``."""
    if i + 1 >= len(src):
        raise JavaRegexError("pattern ends with a backslash")
    char = src[i + 1]
    sets = _set_escape(char)
    if sets is not None:
        return sets, "", 2
    prop = _PROPERTY.match(src, i)
    if prop:
        ranges, raw = _property(prop, ci)
        return ranges, raw, prop.end() - i
    return _literal_escape(src, i, char)


def _literal_escape(src: str, i: int, char: str) -> tuple[RangeList | None, str, int]:
    """A class escape that names one character (or an octal/back-reference digit)."""
    hexed = _hex_escape(src, i)
    if hexed:
        return [(hexed[0], hexed[0])], "", hexed[1]
    if char in SIMPLE_ESCAPES:
        return [(SIMPLE_ESCAPES[char],) * 2], "", 2
    if char.isdigit() and char.isascii():
        return None, f"\\{char}", 2
    if _is_ascii_letter(char):
        raise JavaRegexError(f"unsupported escape \\{char}")
    return [(ord(char),) * 2], "", 2


def _class_atom(src: str, i: int, ci: bool) -> tuple[RangeList | None, str, int]:
    """One class element at ``i``: a single char, an escape or a nested-class error."""
    char = src[i]
    if char == "\\":
        return _class_escape(src, i, ci)
    if char == "[" or src.startswith("&&", i):
        raise JavaRegexError("nested classes and && are not supported")
    return [(ord(char),) * 2], "", 1


def _single(ranges: RangeList | None) -> int | None:
    """The code point of a one-char item, else ``None``."""
    if ranges is not None and len(ranges) == 1 and ranges[0][0] == ranges[0][1]:
        return ranges[0][0]
    return None


def _class_range(src: str, i: int, first: int, ci: bool) -> tuple[Range, int] | None:
    """The range ``first-X`` whose ``-`` sits at ``i``, as ``(range, next index)``."""
    if i + 1 >= len(src) or src[i] != "-" or src[i + 1] == "]":
        return None
    ranges, _raw, length = _class_atom(src, i + 1, ci)
    last = _single(ranges)
    if last is None:
        return None
    if last < first:
        raise JavaRegexError("illegal character range")
    return (first, last), i + 1 + length


def _parse_class(src: str, start: int, ci: bool) -> tuple[str, int]:
    """Translate the class opening at ``src[start] == '['``; returns text and next index."""
    i = start + 1
    negated = src.startswith("^", i)
    i += negated
    items = _Class()
    while i < len(src) and src[i] != "]":
        ranges, raw, length = _class_atom(src, i, ci)
        i += length
        first = _single(ranges)
        span = _class_range(src, i, first, ci) if first is not None else None
        if span:
            ranges, i = [span[0]], span[1]
        items.ranges.extend(_fold(ranges, ci) if ranges else [])
        items.raws.append(raw)
    if i >= len(src) or not (items.ranges or any(items.raws)):
        raise JavaRegexError("empty or unclosed character class")
    return class_text(items.ranges, items.raws, negated), i + 1


def _apply_flags(spec: str, ci: bool) -> bool:
    """New case mode after a ``(?flags)`` group; only ``i`` is supported."""
    on, _, off = spec.partition("-")
    if set(on + off) - {"i"}:
        raise JavaRegexError(f"unsupported inline flags (?{spec})")
    return True if "i" in on else False if "i" in off else ci


class _Translator:
    """One pass over the source; ``ci`` is the case mode of the group being read."""

    def __init__(self, src: str, ci: bool, end_anchor: str) -> None:
        self.src, self.ci, self.i = src, ci, 0
        self.end_anchor = end_anchor
        self.out: list[str] = []
        self.saved: list[bool] = []

    def run(self) -> str:
        while self.i < len(self.src):
            char = self.src[self.i]
            if char == "\\":
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

    def plain(self, char: str) -> None:
        if char == ")":
            self.ci = self.saved.pop() if self.saved else self.ci
            self.emit(char)
        elif char == ".":
            self.emit(DOT)
        elif char == "$":
            self.emit(self.end_anchor)
        elif self.ci and char.isascii() and char.isalpha():
            self.emit(f"[{char.lower()}{char.upper()}]")
        else:
            self.emit(char)

    def group(self) -> None:
        found = _GROUP.match(self.src, self.i)
        if found is None or (found.group() == "(" and self.src.startswith("?", self.i + 1)):
            raise JavaRegexError("malformed group")
        length = found.end() - found.start()
        if found.group("flags") is not None:
            self.flag_group(found, length)
        elif found.group("call") is not None or found.group("comment") is not None:
            text = found.group()
            backref = text.startswith("(?P=")
            self.emit(f"(?i:{text})" if backref and self.ci else text, length)
        else:
            self.saved.append(self.ci)
            self.emit(found.group(), length)

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
            raise JavaRegexError("pattern ends with a backslash")
        char = src[i + 1]
        if char in "dDwWsS":
            self.emit(class_text(_set_base(char) or [], negated=char.isupper()), 2)
        elif char in "bB":
            self.emit(WORD_BOUNDARY if char == "b" else NOT_WORD_BOUNDARY, 2)
        elif char in "pP":
            self.property_escape()
        elif char in "Zz":
            self.emit(self.end_anchor if char == "Z" else ABSOLUTE_END, 2)
        else:
            self.other_escape(char)

    def property_escape(self) -> None:
        match = _PROPERTY.match(self.src, self.i)
        if match is None:
            raise JavaRegexError("malformed property escape")
        ranges, raw = _property(match, self.ci)
        self.emit(class_text(ranges) if ranges is not None else raw, match.end() - self.i)

    def other_escape(self, char: str) -> None:
        src, i = self.src, self.i
        named = _BACKREF_NAME.match(src, i)
        if named or char in "123456789":
            self.backreference(named)
            return
        hexed = _hex_escape(src, i)
        if hexed:
            self.hex_escape(hexed)
        elif char in SIMPLE_ESCAPES or not _is_ascii_letter(char):
            self.emit(src[i : i + 2], 2)
        else:
            raise JavaRegexError(f"unsupported escape \\{char}")

    def backreference(self, named: re.Match[str] | None) -> None:
        """``\\1`` or ``\\k<name>``; Python's ``regex`` spells the latter ``(?P=name)``."""
        length = len(named.group()) if named else 2
        text = f"(?P={named.group()[3:-1]})" if named else self.src[self.i : self.i + 2]
        self.emit(f"(?i:{text})" if self.ci else text, length)

    def hex_escape(self, hexed: tuple[int, int]) -> None:
        """``\\xHH`` and friends, folded to a two-case class for ASCII letters under ``ci``."""
        letter = chr(hexed[0])
        text = self.src[self.i : self.i + hexed[1]]
        folded = self.ci and _is_ascii_letter(letter)
        self.emit(f"[{letter.lower()}{letter.upper()}]" if folded else text, hexed[1])


def to_python(pattern: str, *, ci: bool = False, end_anchor: str = END_ANCHOR) -> str:
    """Python ``regex`` source with the semantics Java gives ``pattern``.

    ``ci`` is ``Pattern.CASE_INSENSITIVE`` (ASCII folding) for the whole pattern; inline
    ``(?i:...)`` / ``(?-i:...)`` groups switch it locally. Raises ``JavaRegexError`` for
    Java syntax outside the supported subset (see the module docstring).
    """
    return _Translator(pattern, ci, end_anchor).run()


def literal_to_python(text: str, *, ci: bool = False) -> str:
    """Python ``regex`` source matching ``text`` exactly, folding ASCII case under ``ci``."""
    out: list[str] = []
    for char in text:
        if ci and char.isascii() and char.isalpha():
            out.append(f"[{char.lower()}{char.upper()}]")
        else:
            out.append(regex.escape(char))
    return "".join(out)


def line_pattern(body: str) -> str:
    """``body`` as Java's ``^body$`` sees a line: one final terminator may follow it.

    ``$`` (no MULTILINE) matches at the end or before a final line terminator, so
    ``find()`` of ``^X$`` accepts ``X`` followed by one of ``\\r\\n \\n \\r U+0085 U+2028
    U+2029``. Use with ``fullmatch``.
    """
    return f"(?:{body}){LINE_TERMINATOR}?"


__all__ = [
    "JavaRegexError",
    "cp_text",
    "line_pattern",
    "literal_to_python",
    "to_python",
]
