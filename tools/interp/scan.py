"""Deadline-aware matching and multiline end detection.

Mirrors ``command/PSystemCommandFactory.java:268-286`` (``isMultilineCommandOk``): lines
are appended one unit at a time (``:288-307`` glues ``{{ ... }}`` embedded diagrams into
one unit), the command is re-validated after each unit, and ``NOT_OK`` / running out of
lines drops the candidate so the next command is tried.

* ``multiline``: ``command/CommandMultilines2.java:79-110`` (and
  ``CommandMultilines.java:58-74``): one line is always ``OK_PARTIAL``; with more lines,
  ``OK`` iff the *last* line, trimmed, fully matches the ``end`` pattern. Only the last
  line is tested, so cost is one regex per appended line.
* ``multiline-bracket``: ``command/CommandMultilinesBracket.java:64-96``: bracket depth
  starts at 1; each later trimmed line ending in ``{`` adds one, ending in ``}`` removes
  one; below 0 is ``NOT_OK``; ``OK`` when depth returns to 0. Depth is maintained
  incrementally here instead of recomputed (same result, linear time).

* ``multiline`` + ``join``: ``command/CommandDecoratorMultine.java:77-93`` with the cap at
  ``PSystemCommandFactory.java:281``: units 1..k (k <= max_lines + 1) are joined with
  U+E100 (``utils/BlocLines.java:296``) and must fully match ``parts``; the smallest k
  wins, k = 1 is the single-line case, and no match within the cap drops the command.

Factories that are not ``PSystemCommandFactory`` subclasses (``PSystemAbstractFactory``
readers such as ``JsonDiagramFactory`` / ``FilesDiagramFactory``, which take plain lines
from ``jsondiagram/StyleExtractor.java:63-103``) do not glue ``{{ ... }}``: the scanners
take ``glue=False`` for their rules.

Known gaps (not representable in the model): ``isLineConsistent`` (abstract, per
command), ``finalVerification`` hooks, and the ``MultilinesStrategy.REMOVE_STARTING_QUOTE`` line
filter (``MultilinesStrategy.java``; ``'`` lines are already gone, see ``source``).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tools.interp.source import Line, embedded_type, is_embedded_end

BRACKET_OPEN = "{"
BRACKET_CLOSE = "}"
JOINER = "\ue100"


class BlockTimeout(Exception):  # noqa: N818 - control-flow signal, not an error
    """The per-block time budget is spent."""


class Deadline:
    """A per-block budget; every regex call receives the remaining time."""

    def __init__(self, timeout_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._limit = clock() + timeout_s

    def fullmatch(self, pattern: Any, text: str) -> bool:
        """Whole-string match; raises ``BlockTimeout`` when the budget runs out."""
        remaining = self._limit - self._clock()
        if remaining <= 0:
            raise BlockTimeout
        try:
            return pattern.fullmatch(text, timeout=remaining) is not None
        except TimeoutError as exc:
            raise BlockTimeout from exc

    def prefix(self, pattern: Any, text: str) -> bool:
        """Could ``text`` still be extended to a full match (``regex`` partial matching)?"""
        remaining = self._limit - self._clock()
        if remaining <= 0:
            raise BlockTimeout
        try:
            return pattern.fullmatch(text, partial=True, timeout=remaining) is not None
        except TimeoutError as exc:
            raise BlockTimeout from exc


@dataclass(frozen=True)
class Join:
    """A ``join`` rule: the pattern for the joined lines and the line cap.

    ``glue_units`` is false for factories that are not ``PSystemCommandFactory``
    subclasses: they read plain lines, so ``{{ ... }}`` is not one unit
    (see ``tools.interp.factories``).
    """

    start: Any
    max_lines: int
    glue_units: bool = True


def unit_end(body: list[Line], j: int, glue: bool = True) -> int:
    """End (exclusive) of the unit starting at ``j`` (``PSystemCommandFactory.java:288``).

    With ``glue`` false every line is its own unit.
    """
    if not glue or embedded_type(body[j].text) is None:
        return j + 1
    nested = 1
    for k in range(j + 1, len(body)):
        if embedded_type(body[k].text) is not None:
            nested += 1
        elif is_embedded_end(body[k].text):
            nested -= 1
            if nested == 0:
                return k + 1
    return len(body)


def scan_multiline(
    end: Any, body: list[Line], i: int, deadline: Deadline, glue: bool = True
) -> int | None:
    """Index after a ``multiline`` command starting at ``i``, or ``None`` (dropped)."""
    j = i
    while j < len(body):
        j = unit_end(body, j, glue)
        if j - i > 1 and deadline.fullmatch(end, body[j - 1].trimmed):
            return j
    return None


def scan_bracket(body: list[Line], i: int, glue: bool = True) -> int | None:
    """Index after a ``multiline-bracket`` command starting at ``i``, or ``None``."""
    level = 1
    j = i
    while j < len(body):
        nxt = unit_end(body, j, glue)
        for k in range(max(j, i + 1), nxt):
            text = body[k].trimmed
            level += text.endswith(BRACKET_OPEN) - text.endswith(BRACKET_CLOSE)
            if level < 0:
                return None
        j = nxt
        if j - i > 1 and level == 0:
            return j
    return None


def scan_join(join: Join, body: list[Line], i: int, deadline: Deadline) -> int | None:
    """Index after a ``join`` command starting at ``i``, or ``None`` (dropped)."""
    j = i
    for _ in range(join.max_lines + 1):
        if j >= len(body):
            return None
        j = unit_end(body, j, join.glue_units)
        joined = JOINER.join(line.trimmed for line in body[i:j])
        if deadline.fullmatch(join.start, joined):
            return j
        # No extension of joined + JOINER can match, so no larger k can: stop early.
        # Without this an uncapped join is O(n^2) per line on long blocks.
        if not deadline.prefix(join.start, joined + JOINER):
            return None
    return None
