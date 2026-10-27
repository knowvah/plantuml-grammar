"""Expand PCRE definition groups and subroutine calls into plain Java-syntax regexes.

JavaScript has neither ``(?(DEFINE)...)`` nor ``(?&name)`` (decision D3, contract C3 in
``plans/ts-engine/contracts.md``). ``expand_subroutines`` runs on Java-syntax text, before
``tools.model.java_regex_js.to_js``: it removes the single DEFINE group and replaces every
``(?&name)`` with ``(?:<body>)``. Non-recursive calls inline exactly. A recursive call is
allowed ``max_depth`` activations of the same name along one call path; the next one
becomes ``(?:(?!))`` (never matches, wrapped so a following quantifier stays valid in
JavaScript), so nesting deeper than ``max_depth`` is rejected: a documented divergence from
the PCRE original. A pattern without ``(?(DEFINE)`` is returned unchanged.

Named groups inside a definition are demoted to ``(?:`` when inlined (an inlined body would
otherwise repeat the name). A back reference or call to such a name raises ``Unsupported``,
as does a result over ``MAX_EXPANDED_BYTES``. Escapes and ``[...]`` classes are skipped
while scanning; ``\\Q...\\E`` is not recognised (no model regex with a DEFINE uses it).

Measured at the ``tools/config.py`` corpora (vega, plantuml-ts, pdiff) and ``tests/fixtures``
(``tests/model/test_js_subroutines.py``, ``@pytest.mark.corpus``). Depth is the number of
activations of one definition; a bracket (JSON) or paren (regex) nesting of ``k`` needs
``k + 1``. Observed (deepest matched text, a bracket/paren-nesting measure for the first
two rows, exact minimal depth against the original for the others):

=====================  ========  ===========  =========================  =================
pattern                observed  expanded at  expanded at ``MAX_DEPTH``   Python compile
=====================  ========  ===========  =========================  =================
CO_JSON_BLOCK_BODY     9         4: 140671 B  Unsupported (> 256 KB)      0.48 s at 4
CO_JSON_DATA_INVALID   4         4: 96387 B   Unsupported (> 256 KB)      0.30 s at 4
RX_WELL_FORMED         6         7: 129331 B  Unsupported (> 256 KB)      1.47 s at 7
RX_EMPTY               1         11: 1653 B   expands                     0.004 s
RX_BALANCED            6         11: 5655 B   expands                     0.021 s
=====================  ========  ===========  =========================  =================

``MAX_DEPTH`` = 9 + 2 = 11. The three patterns marked Unsupported fall back, and corpus text
reaches all three (CO_JSON_BLOCK_BODY: two pdiff files nest 8 deep, ``dbhum/k_id/
kidoki-70-fala224.puml`` and ``dbhum/n_op/nopoku-31-cisi925.puml``; the next deepest corpus
nesting, 4, still needs depth 5 > 4). The largest depth that fits 256 KB is 4 for the JSON
patterns (size grows about 4x per level), 8 for RX_WELL_FORMED (259635 B of UTF-8).

Per-pattern depths (decision D3a, contract C3a): ``depth_for`` returns observed + 2, capped
by the largest depth that fits 256 KB. The table is keyed by the SHA-256 of the exact Java
source in the model YAML (the sources are 2-4 KB each; a test recomputes the digests from
the YAML, so an edited pattern fails loudly and falls back to ``MAX_DEPTH`` otherwise):

=====================  ===========  =========  =====================
pattern                observed+2   depth_for  expanded size
=====================  ===========  =========  =====================
CO_JSON_BLOCK_BODY     11           4          140671 B
CO_JSON_DATA_INVALID   6            4          96387 B
RX_WELL_FORMED         8            8          259635 B
RX_EMPTY               3            3          485 B
RX_BALANCED            8            8          4125 B
=====================  ===========  =========  =====================

The two JSON leaves are recognised natively in TypeScript at any depth, so their depth 4
(``FAST_DEPTH``) expansion is only a fast path whose answer is final in one direction
(``fast_final``): ``accept`` for CO_JSON_BLOCK_BODY (recursion in positive position, the
bounded expansion matches a subset) and ``reject`` for CO_JSON_DATA_INVALID (recursion under
a negative lookahead, the bounded expansion matches a superset).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal

MAX_DEPTH = 11
FAST_DEPTH = 4
MAX_EXPANDED_BYTES = 256 * 1024
JSON_BLOCK_BODY_KIND = "json-block-body"
JSON_DATA_INVALID_KIND = "json-data-invalid"
REGEX_WELL_FORMED_KIND = "regex-well-formed"
# SHA-256 of the Java source of each DEFINE pattern in the model YAML -> (depth, kind).
_DIGEST_BLOCK = "6f5ea8273a28641d680f7f65b616d254b148f24be86395684e7f8bebd79e5bb1"
_DIGEST_INVALID = "656b964e213e29a04d3d4676c28dd1547585460baf9fafa8ae70bc76b8c210bd"
_DIGEST_WELL_FORMED = "ea123ce1a36033b0eaacaf08e1022690f759a14049c8652a0b03efaa79bcbbb6"
_DIGEST_EMPTY = "ee9b7af0844ee471478cd312730e5b5d61cbb61bf6c1360d90d09866da6731d7"
_DIGEST_BALANCED = "4389cb35ca3eedd993fda1b3dfd8faddf1fd50d18d78e371b051215aba696889"
PATTERN_DEPTHS = {
    _DIGEST_BLOCK: FAST_DEPTH,
    _DIGEST_INVALID: FAST_DEPTH,
    _DIGEST_WELL_FORMED: 8,
    _DIGEST_EMPTY: 3,
    _DIGEST_BALANCED: 8,
}
_NATIVE_KINDS = {
    _DIGEST_BLOCK: JSON_BLOCK_BODY_KIND,
    _DIGEST_INVALID: JSON_DATA_INVALID_KIND,
    _DIGEST_WELL_FORMED: REGEX_WELL_FORMED_KIND,
}
_FAST_FINAL: dict[str, Literal["accept", "reject"]] = {
    JSON_BLOCK_BODY_KIND: "accept",
    JSON_DATA_INVALID_KIND: "reject",
    REGEX_WELL_FORMED_KIND: "accept",
}
# Depth of the bounded ``fast`` regex of each native kind; ``None`` means no fast regex, the
# recognizer alone decides (a regex line parses in microseconds, so a fast regex would only
# add its compile time to the first verdict).
FAST_DEPTHS: dict[str, int | None] = {
    JSON_BLOCK_BODY_KIND: FAST_DEPTH,
    JSON_DATA_INVALID_KIND: FAST_DEPTH,
    REGEX_WELL_FORMED_KIND: None,
}
NEVER_MATCHES = "(?:(?!))"
DEFINE_OPEN = "(?(DEFINE)"
NON_CAPTURING = "(?:"

_CALL = re.compile(r"\(\?&(\w+)\)")
_NAMED = re.compile(r"\(\?<([A-Za-z][A-Za-z0-9]*)>")
_NAME_REFS = re.compile(r"\\k<(\w+)>|\(\?P=(\w+)\)|\(\?P>(\w+)\)|\\g<(\w+)>|\(\?&(\w+)\)")


class Unsupported(ValueError):
    """The pattern cannot be expanded; ``reason`` says why."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _class_end(text: str, start: int) -> int:
    """Index just past the ``[...]`` class opening at ``text[start]``."""
    depth, i = 0, start
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 1
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise Unsupported("unclosed character class")


def _open_parens(text: str) -> Iterator[int]:
    """Indexes of every ``(`` that is neither escaped nor inside a class."""
    i = 0
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2
        elif char == "[":
            i = _class_end(text, i)
        else:
            if char == "(":
                yield i
            i += 1


def _group_end(text: str, start: int) -> int:
    """Index of the ``)`` closing the group that opens at ``text[start]``."""
    depth = 0
    i = start
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2
            continue
        if char == "[":
            i = _class_end(text, i)
            continue
        depth += char == "("
        depth -= char == ")"
        if depth == 0:
            return i
        i += 1
    raise Unsupported(f"unclosed group at offset {start}")


def _matches(text: str, pattern: re.Pattern[str]) -> list[re.Match[str]]:
    """Non-overlapping matches of ``pattern`` that start at an active ``(``."""
    found: list[re.Match[str]] = []
    end = 0
    for i in _open_parens(text):
        match = pattern.match(text, i) if i >= end else None
        if match:
            found.append(match)
            end = match.end()
    return found


def _split_define(pattern: str) -> tuple[str, dict[str, str], str] | None:
    """``(before, {name: body}, after)`` around the DEFINE group, or ``None`` without one."""
    starts = [i for i in _open_parens(pattern) if pattern.startswith(DEFINE_OPEN, i)]
    if not starts:
        return None
    if len(starts) > 1:
        raise Unsupported("more than one (?(DEFINE) group")
    start = starts[0]
    end = _group_end(pattern, start)
    inner = pattern[start + len(DEFINE_OPEN) : end]
    bodies: dict[str, str] = {}
    pos = 0
    while pos < len(inner):
        head = _NAMED.match(inner, pos)
        if head is None:
            raise Unsupported(f"DEFINE holds something other than a named group at {pos}")
        close = _group_end(inner, pos)
        if head.group(1) in bodies:
            raise Unsupported(f"definition {head.group(1)} appears twice")
        bodies[head.group(1)] = inner[head.end() : close]
        pos = close + 1
    return pattern[:start], bodies, pattern[end + 1 :]


def _demote(body: str) -> tuple[str, set[str]]:
    """``body`` with its named groups made non-capturing, and the names removed."""
    out: list[str] = []
    names: set[str] = set()
    last = 0
    for match in _matches(body, _NAMED):
        out.append(body[last : match.start()])
        out.append(NON_CAPTURING)
        names.add(match.group(1))
        last = match.end()
    out.append(body[last:])
    return "".join(out), names


@dataclass
class _Expander:
    bodies: dict[str, str]
    max_depth: int
    memo: dict[tuple[str, tuple[int, ...]], str] = field(default_factory=dict)

    def inline(self, text: str, counts: tuple[int, ...]) -> str:
        """``text`` with each ``(?&name)`` replaced by its expansion."""
        out: list[str] = []
        last = 0
        for match in _matches(text, _CALL):
            out.append(text[last : match.start()])
            out.append(self.call(match.group(1), counts))
            last = match.end()
        out.append(text[last:])
        return _checked("".join(out))

    def call(self, name: str, counts: tuple[int, ...]) -> str:
        """The expansion of one call, given the activation count of every definition."""
        names = list(self.bodies)
        if name not in self.bodies:
            raise Unsupported(f"call to undefined subroutine {name}")
        index = names.index(name)
        inner = (*counts[:index], counts[index] + 1, *counts[index + 1 :])
        if inner[index] > self.max_depth:
            return NEVER_MATCHES
        key = (name, inner)
        if key not in self.memo:
            self.memo[key] = NON_CAPTURING + self.inline(self.bodies[name], inner) + ")"
        return self.memo[key]


def _checked(text: str) -> str:
    size = len(text.encode())
    if size > MAX_EXPANDED_BYTES:
        raise Unsupported(f"expansion is over {MAX_EXPANDED_BYTES} bytes")
    return text


def _digest(pattern: str) -> str:
    return hashlib.sha256(pattern.encode()).hexdigest()


def depth_for(pattern: str) -> int:
    """Measured expansion depth of a known model pattern, else ``MAX_DEPTH``."""
    return PATTERN_DEPTHS.get(_digest(pattern), MAX_DEPTH)


def native_kind(pattern: str) -> str | None:
    """The native recognizer kind of a JSON or regex-diagram leaf, else ``None``."""
    return _NATIVE_KINDS.get(_digest(pattern))


def fast_final(pattern: str) -> Literal["accept", "reject"]:
    """The answer of the ``FAST_DEPTH`` expansion that is final for a native leaf.

    Raises:
        ValueError: ``pattern`` is not a native leaf.
    """
    kind = native_kind(pattern)
    if kind is None:
        raise ValueError("pattern is not a native leaf")
    return _FAST_FINAL[kind]


def fast_depth(pattern: str) -> int | None:
    """Depth of the ``fast`` regex of a native leaf, or ``None`` for no fast regex.

    Raises:
        ValueError: ``pattern`` is not a native leaf.
    """
    kind = native_kind(pattern)
    if kind is None:
        raise ValueError("pattern is not a native leaf")
    return FAST_DEPTHS[kind]


def expand_subroutines(pattern: str, max_depth: int | None = None) -> str:
    """Return ``pattern`` with no ``(?(DEFINE)`` and no ``(?&``.

    Args:
        pattern: Java-syntax regex, possibly with one DEFINE group and ``(?&name)`` calls.
        max_depth: activations of one definition allowed along a call path; the next
            call never matches. ``None`` means ``depth_for(pattern)``.

    Raises:
        Unsupported: malformed or unsupported DEFINE use, or a result over ``MAX_EXPANDED_BYTES``.
    """
    parts = _split_define(pattern)
    if parts is None:
        return pattern
    if max_depth is None:
        max_depth = depth_for(pattern)
    before, raw_bodies, after = parts
    bodies: dict[str, str] = {}
    demoted: set[str] = set()
    for name, body in raw_bodies.items():
        bodies[name], names = _demote(body)
        demoted |= names
    for text in (before, after, *raw_bodies.values()):
        for match in _NAME_REFS.finditer(text):
            ref = next(g for g in match.groups() if g)
            if ref in demoted:
                raise Unsupported(f"group {ref} inside a definition is referenced by name")
    expander = _Expander(bodies, max_depth)
    zero = (0,) * len(bodies)
    return expander.inline(before, zero) + expander.inline(after, zero)
