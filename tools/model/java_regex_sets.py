"""Code point sets for the Java regex translation (``tools.model.java_regex``).

Everything here is a pure function over sorted, non-overlapping ``(lo, hi)`` ranges.
The POSIX table is Java's: ``java.util.regex.Pattern`` documents ``\\p{Alpha}``,
``\\p{Digit}`` ... as ASCII-only classes (JDK 21 "POSIX character classes (US-ASCII
only)"), where Python's ``regex`` reads the same names as Unicode properties.
"""

from __future__ import annotations

from collections.abc import Iterable

Range = tuple[int, int]
RangeList = list[Range]

MAX_CODE_POINT = 0x10FFFF
CASE_OFFSET = 0x20
UPPER: Range = (0x41, 0x5A)
LOWER: Range = (0x61, 0x7A)
DIGIT: Range = (0x30, 0x39)
SPACE_RANGES: RangeList = [(0x09, 0x0D), (0x20, 0x20)]
WORD_RANGES: RangeList = [DIGIT, UPPER, (0x5F, 0x5F), LOWER]
PUNCT_RANGES: RangeList = [(0x21, 0x2F), (0x3A, 0x40), (0x5B, 0x60), (0x7B, 0x7E)]

# Java's POSIX classes; each is a fixed ASCII set.
POSIX_CLASSES: dict[str, RangeList] = {
    "Lower": [LOWER],
    "Upper": [UPPER],
    "ASCII": [(0x00, 0x7F)],
    "Alpha": [UPPER, LOWER],
    "Digit": [DIGIT],
    "Alnum": [DIGIT, UPPER, LOWER],
    "Punct": PUNCT_RANGES,
    "Graph": [(0x21, 0x7E)],
    "Print": [(0x20, 0x7E)],
    "Blank": [(0x09, 0x09), (0x20, 0x20)],
    "Cntrl": [(0x00, 0x1F), (0x7F, 0x7F)],
    "XDigit": [DIGIT, (0x41, 0x46), (0x61, 0x66)],
    "Space": SPACE_RANGES,
}


def merge(ranges: Iterable[Range]) -> RangeList:
    """Sorted, non-overlapping, non-adjacent ranges covering the same code points."""
    merged: RangeList = []
    for lo, hi in sorted(ranges):
        if merged and lo <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


def complement(ranges: Iterable[Range]) -> RangeList:
    """Every code point (U+0000..U+10FFFF) not in ``ranges``."""
    out: RangeList = []
    next_free = 0
    for lo, hi in merge(ranges):
        if lo > next_free:
            out.append((next_free, lo - 1))
        next_free = hi + 1
    if next_free <= MAX_CODE_POINT:
        out.append((next_free, MAX_CODE_POINT))
    return out


def fold_ascii(ranges: Iterable[Range]) -> RangeList:
    """Add the other-case twin of every ASCII letter, and nothing else.

    ``Pattern.CASE_INSENSITIVE`` without ``UNICODE_CASE`` folds ASCII only
    (``Pattern.CIRange`` / ``SingleI``): U+212A does not match ``k``, U+00C9 does not
    match U+00E9.
    """
    base = list(ranges)
    extra: RangeList = []
    for lo, hi in base:
        if max(lo, UPPER[0]) <= min(hi, UPPER[1]):
            extra.append((max(lo, UPPER[0]) + CASE_OFFSET, min(hi, UPPER[1]) + CASE_OFFSET))
        if max(lo, LOWER[0]) <= min(hi, LOWER[1]):
            extra.append((max(lo, LOWER[0]) - CASE_OFFSET, min(hi, LOWER[1]) - CASE_OFFSET))
    return merge(base + extra)


def cp_text(cp: int) -> str:
    """A code point as regex text.

    ASCII alphanumerics are literal and ASCII punctuation is backslash-escaped (never
    ``\\xHH``: a consumer that unescapes ``\\x5c``/``\\x5d``/``\\x2d`` before compiling
    would read class syntax). Controls, space and everything non-ASCII use ``\\xHH`` /
    ``\\uHHHH`` / ``\\UHHHHHHHH``.
    """
    char = chr(cp)
    if char.isascii() and char.isalnum():
        return char
    if char.isascii() and char.isprintable() and char != " ":
        return "\\" + char
    if cp <= 0xFF:
        return f"\\x{cp:02x}"
    if cp <= 0xFFFF:
        return f"\\u{cp:04x}"
    return f"\\U{cp:08x}"


def ranges_text(ranges: Iterable[Range]) -> str:
    """The body of a ``[...]`` class for ``ranges``."""
    parts: list[str] = []
    for lo, hi in merge(ranges):
        if lo == hi:
            parts.append(cp_text(lo))
        elif hi == lo + 1:
            parts.append(cp_text(lo) + cp_text(hi))
        else:
            parts.append(f"{cp_text(lo)}-{cp_text(hi)}")
    return "".join(parts)


def class_text(ranges: Iterable[Range], raws: Iterable[str] = (), negated: bool = False) -> str:
    """A complete ``[...]`` class from ranges plus raw items such as ``\\p{L}``."""
    return "[" + ("^" if negated else "") + ranges_text(ranges) + "".join(raws) + "]"
