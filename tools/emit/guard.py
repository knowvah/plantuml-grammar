"""Guards: small regexes tested before a large engine pattern, rejecting lines early (#4).

V8 compiles a regex on its first execution, at a cost that grows with its size, so a few
large patterns dominate the time to a first verdict. A guard is a necessary condition of
its pattern: when the guard fails the pattern cannot match, and the engine skips it
without compiling it. When the guard passes, the pattern decides as before, so verdicts
do not change.

The guard of a Part is built from its head: a Part ``H`` with ``L(P)`` contained in
``L(H)`` followed by anything. For ``seq`` that is the leading children (the last one
possibly a head itself), for ``alt`` the alternation of the alternatives' heads, for
``plus`` the head of its body; ``opt``, ``star`` and leaves are kept whole or not at all.
This holds for backtracking regexes too: a match of ``P`` runs one successful path
through its leading children, and that path is a match of ``H``; lookarounds see the
same input in both. A native JSON leaf is never part of a head, because its JS regex is
a bounded approximation (``js_subroutines.FAST_DEPTH``).

- Start pattern ``^(?:P)LT?$``: guard ``^(?:H)``.
- Join prefix (every prefix of a match of ``P``): a prefix ``s`` of ``w`` in ``L(P)`` is
  a prefix of ``w``'s head part or starts with it, so the guard is
  ``prefix(H) | ^(?:H)``.

A head that matches the empty string restricts nothing and is dropped.
"""

from __future__ import annotations

from collections.abc import Callable

import regex

from tools.interp.compile import part_to_regex
from tools.model import Part

ENCODING = "utf-8"
GUARD_MIN_BYTES = 8 * 1024
GUARD_MAX_BYTES = 1024
# The "(?:" and ")" that wrap the JS of every seq and alt Part.
WRAP_BYTES = 4

JsOf = Callable[[Part], str]
IsNative = Callable[[Part], bool]


def _size(text: str) -> int:
    return len(text.encode(ENCODING))


class _Heads:
    def __init__(self, js: JsOf, is_native: IsNative) -> None:
        self._js = js
        self._is_native = is_native

    def _fits(self, part: Part, budget: int) -> bool:
        return not self._has_native(part) and _size(self._js(part)) <= budget

    def _has_native(self, part: Part) -> bool:
        for key in ("seq", "alt"):
            if key in part:
                return any(self._has_native(child) for child in part[key])
        for key in ("opt", "star", "plus"):
            if key in part:
                return self._has_native(part[key])
        return self._is_native(part)

    def head(self, part: Part, budget: int) -> Part | None:
        """A head of ``part`` within ``budget`` bytes of JS, or None when there is none."""
        if self._fits(part, budget):
            return part
        if "seq" in part:
            return self._seq(part["seq"], budget)
        if "alt" in part:
            return self._alt(part["alt"], budget)
        if "plus" in part:
            return self.head(part["plus"], budget)
        return None

    def _seq(self, children: list[Part], budget: int) -> Part | None:
        kept: list[Part] = []
        used = WRAP_BYTES
        for child in children:
            if self._fits(child, budget - used):
                kept.append(child)
                used += _size(self._js(child))
                continue
            inner = self.head(child, budget - used)
            if inner is not None:
                kept.append(inner)
            break
        return {"seq": kept} if kept else None

    def _alt(self, options: list[Part], budget: int) -> Part | None:
        share = (budget - WRAP_BYTES - len(options) + 1) // len(options)
        heads = [self.head(option, share) for option in options]
        if any(h is None for h in heads):
            return None
        return {"alt": heads}


def _restricts(head: Part) -> bool:
    """False when the head matches the empty string (it would let every line through)."""
    return regex.compile(part_to_regex(head)).match("") is None


def guard_head(part: Part, js: JsOf, is_native: IsNative) -> Part | None:
    """The head the guard is built from, or None when no useful guard exists."""
    head = _Heads(js, is_native).head(part, GUARD_MAX_BYTES)
    if head is None or not _restricts(head):
        return None
    return head


def start_guard(head_js: str) -> str:
    """Guard of a whole-line start pattern, from the head's JS body."""
    return f"^(?:{head_js})"


def prefix_guard(head_prefix: str, head_js: str) -> str:
    """Guard of a join prefix pattern, from the head's prefix pattern and JS body."""
    return f"{head_prefix}|^(?:{head_js})"


__all__ = [
    "GUARD_MAX_BYTES",
    "GUARD_MIN_BYTES",
    "guard_head",
    "prefix_guard",
    "start_guard",
]
