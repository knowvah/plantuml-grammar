"""Compiled rules of a resolved model, built lazily per context and cached.

``trim: false`` (``untrimmed``) mirrors ``SingleLineCommand2(doTrim=false)``: the pattern
is matched against ``Line.text``, the line as the command loop receives it
(``SingleLineCommand2.java:76-81`` ``myTrim2`` returns the ``StringLocated`` untouched,
``:93`` and ``:102`` match it), instead of ``Line.trimmed`` (``getTrimmed``, ``trin``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.interp.compile import compile_part
from tools.interp.factories import NON_COMMAND_FACTORIES
from tools.interp.scan import Deadline, Join, scan_bracket, scan_join, scan_multiline
from tools.interp.source import Line
from tools.model import Entry, ResolvedModel

KIND_SINGLE = "single"
KIND_MULTILINE = "multiline"
KIND_BRACKET = "multiline-bracket"
KIND_OPAQUE = "opaque"
ACTION_PUSH = "push"
ACTION_POP = "pop"
ACTION_SET = "set"
ACTION_NONE = ""


@dataclass(frozen=True)
class Rule:
    """One command with its compiled patterns and context transition."""

    name: str
    kind: str
    start: Any
    end: Any
    join: Join | None
    action: str
    target: str
    require_pop: bool = False
    reject: bool = False
    gives: str = ""
    needs: str = ""
    untrimmed: bool = False
    glue_units: bool = True

    def advance(self, body: list[Line], i: int, deadline: Deadline) -> int | None:
        """Index after this command starting at ``i``; ``None`` = no match or dropped."""
        if self.join is not None:
            return scan_join(self.join, body, i, deadline)
        line = body[i].text if self.untrimmed else body[i].trimmed
        if not deadline.fullmatch(self.start, line):
            return None
        if self.kind == KIND_OPAQUE:
            return len(body)
        if self.kind == KIND_MULTILINE:
            return scan_multiline(self.end, body, i, deadline, self.glue_units)
        if self.kind == KIND_BRACKET:
            return scan_bracket(body, i, self.glue_units)
        return i + 1


def build_rule(entry: Entry, glue_units: bool = True) -> Rule:
    """Compile a resolved command entry; ``glue_units`` is false for plain-line factories."""
    action, target = ACTION_NONE, ""
    if entry.get("pop"):
        action = ACTION_POP
    for key in (ACTION_PUSH, ACTION_SET):
        if key in entry:
            action, target = key, entry[key]
    end = compile_part(entry["end"]) if "end" in entry else None
    start = compile_part(entry["parts"])
    join = Join(start, entry["join"]["max_lines"], glue_units) if "join" in entry else None
    return Rule(
        entry["command"],
        entry["kind"],
        start,
        end,
        join,
        action,
        target,
        bool(entry.get("require_pop")),
        bool(entry.get("reject")),
        entry.get("gives", ""),
        entry.get("needs", ""),
        entry.get("trim") is False,
        glue_units,
    )


class RuleBook:
    """Lazily compiled ``context -> [Rule]`` for the given models (read-only)."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], list[Rule]] = {}

    def rules(self, model: ResolvedModel, context: str) -> list[Rule]:
        """Rules of ``context``; ``KeyError`` if the context does not exist."""
        key = (model.id, context)
        if key not in self._cache:
            glue = model.factory not in NON_COMMAND_FACTORIES
            self._cache[key] = [build_rule(e, glue) for e in model.contexts[context]]
        return self._cache[key]
