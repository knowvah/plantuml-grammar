"""PlantUML ``%``-macro expansion and portability checks for expanded patterns.

``expand`` mirrors ``regex/Pattern2.transform`` at 97a5992 exactly.
"""

from __future__ import annotations

import re

import regex

# Jaws.BLOCK_E1_INVISIBLE_QUOTE (jaws/Jaws.java:55).
INVISIBLE_QUOTE = "\ue121"

# regex/Pattern2.java:54-59, non-TeaVM branch (the TeaVM %pLN at :54 is not used).
MACROS: dict[str, str] = {
    "%pLN": "\\p{L}\\p{N}",  # Pattern2.java:56
    "%s": "\\s\u00a0",  # Pattern2.java:57
    "%q": "'\u2018\u2019",  # Pattern2.java:58
    "%g": '"\u201c\u201d' + INVISIBLE_QUOTE,  # Pattern2.java:59
}

# Pattern2.TRANSFORM_PATTERN, Pattern2.java:62.
_TRANSFORM = re.compile(r"%(pLN|s|q|g)")

# Constructs that compile with Java but are rejected or differ in Python re, Oniguruma
# or PCRE. Each entry is (label, pattern over the expanded regex text).
_RISKY: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("class-intersection", re.compile(r"&&")),
    ("quote-escape", re.compile(r"\\[QE]")),
    ("horizontal-space-escape", re.compile(r"\\[hHRXzZG]")),
    ("java-property-class", re.compile(r"\\p\{(?:java|Is|In)")),
    ("inline-flag", re.compile(r"\(\?[a-zA-Z]+\)")),
)
_POSSESSIVE = re.compile(r"(?<!\\)(?:[*+?]|\{\d+(?:,\d*)?\})\+")
_QUOTE_OPEN = "\\Q"
_QUOTE_CLOSE = "\\E"
_REGEX_META = frozenset("\\.^$|?*+()[]{}")
_TOKEN = re.compile(r"\\.|\[(?:\\.|[^\]\\])*\]|[^\\\[]", re.DOTALL)


def expand(pattern: str) -> str:
    """Expand ``%pLN``, ``%s``, ``%q`` and ``%g`` like ``Pattern2.transform``.

    Unknown ``%x`` sequences are left untouched, as upstream leaves them.
    """
    return _TRANSFORM.sub(lambda m: MACROS[m.group()], pattern)


def convert_quotes(pattern: str) -> str:
    """Rewrite Java ``\\Q...\\E`` quoting as backslash-escaped literals.

    ``\\Q`` runs to the first ``\\E`` or the end of the pattern, as in
    ``java.util.regex.Pattern``; only regex metacharacters are escaped.
    """
    out: list[str] = []
    pos = 0
    while True:
        start = pattern.find(_QUOTE_OPEN, pos)
        if start < 0:
            out.append(pattern[pos:])
            return "".join(out)
        out.append(pattern[pos:start])
        stop = pattern.find(_QUOTE_CLOSE, start + len(_QUOTE_OPEN))
        body_end = len(pattern) if stop < 0 else stop
        body = pattern[start + len(_QUOTE_OPEN) : body_end]
        out.append("".join("\\" + c if c in _REGEX_META else c for c in body))
        pos = len(pattern) if stop < 0 else stop + len(_QUOTE_CLOSE)


def portable(pattern: str) -> str:
    """``expand`` followed by the Java-only syntax rewrites (currently ``\\Q...\\E``)."""
    return convert_quotes(expand(pattern))


def _outside_classes(pattern: str) -> str:
    """Pattern with escapes and bracket classes blanked, for quantifier scanning."""
    return "".join(
        tok if len(tok) == 1 else "_" if tok.startswith("\\") else "[]"
        for tok in _TOKEN.findall(pattern)
    )


def portability_issues(expanded: str) -> list[str]:
    """Labels of constructs in an expanded pattern that other engines may reject.

    Includes ``uncompilable`` when even the ``regex`` module cannot compile it.
    """
    issues = [label for label, rx in _RISKY if rx.search(expanded)]
    if _POSSESSIVE.search(_outside_classes(expanded)):
        issues.append("possessive-quantifier")
    try:
        regex.compile(expanded)
    except regex.error:
        issues.append("uncompilable")
    return sorted(issues)
