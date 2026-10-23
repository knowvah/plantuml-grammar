"""Entries no emitter can express: ``reject`` entries and ``join`` entries that need a joiner.

* ``emit: false`` entries are interpreter-only (state heads that would only double the
  derivations of a grammar that keeps the generated rules accepting the same lines); dropped.

* ``reject: true`` entries only make the interpreter fail an attempt (they mirror
  ``CommandExecutionResult.error``); a grammar describes accepted text, so they are dropped.
* A ``multiline`` entry with ``join`` matches several lines joined with U+E100
  (``utils/BlocLines.java:296``). The emitters approximate it by matching ``parts`` against
  one line, but a line never contains U+E100; when every match of ``parts`` must contain it
  (see ``needs_joiner``) the entry can never match and is dropped instead of emitted as
  dead, lookaround-heavy weight.

``needs_joiner`` is deliberately conservative: it answers ``True`` only when U+E100 is a
mandatory element on the path of the Part tree (a ``literal``; a ``seq`` child; every ``alt``
branch; a ``plus`` body; a regex with the character at its top level outside classes and
groups, no top-level ``|`` and no optional quantifier). Anything it cannot prove is kept.
"""

from __future__ import annotations

from collections.abc import Iterator

from tools.model import Entry, Part

JOINER = ""
JOIN_KEY = "join"
REJECT_KEY = "reject"
EMIT_KEY = "emit"
OPTIONAL_QUANTIFIERS = "?*"
ZERO_BRACE = "{0"
GROUP_CHARS = {"(": 1, ")": -1, "|": 0}  # depth change of each group metacharacter


def skipped(entry: Entry) -> bool:
    """True when emitters must drop the command ``entry``."""
    if entry.get(REJECT_KEY) or entry.get(EMIT_KEY) is False:
        return True
    return JOIN_KEY in entry and needs_joiner(entry["parts"])


def needs_joiner(part: Part) -> bool:
    """True when every string matched by ``part`` contains U+E100 (so no single line does)."""
    if "literal" in part:
        return JOINER in part["literal"]
    if "regex" in part:
        return _regex_requires_joiner(part["regex"])
    if "seq" in part:
        return any(needs_joiner(child) for child in part["seq"])
    if "alt" in part:
        return bool(part["alt"]) and all(needs_joiner(child) for child in part["alt"])
    return "plus" in part and needs_joiner(part["plus"])


def class_end(pattern: str, start: int) -> int:
    """Index just after the character class opening at ``start`` (``[``)."""
    i = start + 1
    if pattern[i : i + 1] == "^":
        i += 1
    if pattern[i : i + 1] == "]":  # a leading ']' is a member
        i += 1
    while i < len(pattern) and pattern[i] != "]":
        i += 2 if pattern[i] == "\\" else 1
    return i + 1


def _optional_after(pattern: str, index: int) -> bool:
    follow = pattern[index : index + 2]
    return follow[:1] in tuple(OPTIONAL_QUANTIFIERS) or follow == ZERO_BRACE


def _atoms(pattern: str) -> Iterator[tuple[str, bool, int]]:
    """``(char, escaped, index after)`` for each character outside character classes."""
    i = 0
    while i < len(pattern):
        if pattern[i] == "[":
            i = class_end(pattern, i)
            continue
        step = 2 if pattern[i] == "\\" else 1
        yield pattern[i + step - 1 : i + step], step == 2, i + step
        i += step


def _regex_requires_joiner(pattern: str) -> bool:
    """Top-level U+E100, mandatory, in a pattern without a top-level alternation."""
    depth, found = 0, False
    for char, escaped, after in _atoms(pattern):
        if not escaped and char in GROUP_CHARS:
            if char == "|" and depth == 0:
                return False
            depth += GROUP_CHARS[char]
        elif char == JOINER and depth == 0 and not _optional_after(pattern, after):
            found = True
    return found
