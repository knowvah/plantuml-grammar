"""Flatten model Parts into one TextMate-portable regex with numbered capture groups.

TextMate scopes are attached to *numbered* capture groups, so every group the model's own
regexes contain (plain ``(...)`` or named ``(?P<n>...)`` / ``(?<n>...)``) is demoted to a
non-capturing group, and the flattener adds exactly one capturing group per Part that
carries a ``scope``. Back-references to demoted groups are not supported (the extracted
model has none).
"""

from __future__ import annotations

import re
from importlib import import_module

import regex

from tools.model import Part

SCOPE_SUFFIX = "plantuml"
QUANTIFIERS = {"opt": "?", "star": "*", "plus": "+"}
UNICODE_CATEGORY = re.compile(r"\\p\{[A-Za-z_]+\}")
SRE_PARSE = import_module("re._parser")  # the stdlib's static width analysis
LITERAL_META = frozenset("\\.^$|?*+()[]{}")
NON_CAPTURING = "(?:"
NAMED_OPEN = re.compile(r"\(\?(?:P?<[A-Za-z_]\w*>|'[A-Za-z_]\w*')")
Captures = dict[str, dict[str, str]]


def escape_literal(text: str) -> str:
    """Escape regex metacharacters so ``text`` matches itself in Oniguruma and PCRE."""
    return "".join("\\" + c if c in LITERAL_META else c for c in text)


def _open_group(pattern: str, index: int) -> tuple[int, str]:
    """Rewrite the group opener at ``index``; returns the next index and replacement."""
    named = NAMED_OPEN.match(pattern, index)
    if named:
        return named.end(), NON_CAPTURING
    if pattern.startswith("(?", index):
        return index + 1, "("
    return index + 1, NON_CAPTURING


def demote_groups(pattern: str) -> str:
    """Turn every capturing or named group in ``pattern`` into a non-capturing one."""
    out: list[str] = []
    index = 0
    in_class = False
    while index < len(pattern):
        char = pattern[index]
        step, text = 1, char
        if char == "\\":
            step, text = 2, pattern[index : index + 2]
        elif in_class:
            in_class = char != "]"
        elif char == "[":
            in_class = True
        elif char == "(":
            end, text = _open_group(pattern, index)
            step = end - index
        out.append(text)
        index += step
    return "".join(out)


class Flattener:
    """Accumulates the regex text and ``captures`` map for one or more Parts."""

    def __init__(self) -> None:
        self.captures: Captures = {}
        self._count = 0

    def build(self, part: Part) -> str:
        """Regex text for ``part``; scoped leaves become numbered capture groups."""
        if "seq" in part:
            return "".join(self.build(p) for p in part["seq"])
        if "alt" in part:
            return "(?:" + "|".join(self.build(p) for p in part["alt"]) + ")"
        for key, quantifier in QUANTIFIERS.items():
            if key in part:
                return "(?:" + self.build(part[key]) + ")" + quantifier
        if "regex" in part:
            return self._leaf(part, self._regex_text(part["regex"], bool(part.get("ci"))))
        if "literal" in part:
            text = escape_literal(part["literal"])
            return self._leaf(part, f"(?i:{text})" if part["ci"] else text)
        raise ValueError(f"unknown Part: {sorted(part)}")

    @staticmethod
    def _regex_text(pattern: str, ci: bool) -> str:
        text = demote_groups(pattern)
        if ci:
            return f"(?i:{text})"
        return f"(?:{text})" if "|" in text else text

    def _leaf(self, part: Part, text: str) -> str:
        scope = part.get("scope")
        if not scope:
            return text
        self._count += 1
        self.captures[str(self._count)] = {"name": f"{scope}.{SCOPE_SUFFIX}"}
        return f"({text})"


def flatten(part: Part) -> tuple[str, Captures]:
    """``(regex, captures)`` for one Part."""
    flattener = Flattener()
    return flattener.build(part), flattener.captures


def flatten_alternatives(parts: list[Part]) -> tuple[str, Captures]:
    """``(regex, captures)`` for the ordered alternation of several Parts."""
    return flatten({"alt": parts})


def can_match_empty(pattern: str) -> bool:
    """Whether ``pattern`` can match the empty string (static minimum width of zero).

    Lookarounds count as zero width, so a pattern whose only width comes from a lookbehind
    (``(?=--).*(?<=--)``) is conservatively reported as nullable. A pattern the width
    analysis cannot parse is reported as nullable too: dropping a rule is safe, emitting a
    rule that can match nothing is not.
    """
    # sre_parse cannot read ``\p{..}`` categories; one letter has the same width.
    simple = UNICODE_CATEGORY.sub("A", pattern)
    try:
        try:
            return bool(SRE_PARSE.parse(simple).getwidth()[0] == 0)
        except re.error:
            # Syntax only the ``regex`` module reads: test the empty string directly.
            return regex.compile(simple).match("") is not None
    except (ValueError, OverflowError, re.error, regex.error):
        return True
