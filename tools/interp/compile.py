"""Compile model Parts to whole-line regexes.

Upstream compiles every command regex through ``Pattern2.compileInternal`` with
``Pattern.CASE_INSENSITIVE`` (``regex/Pattern2.java:114`` at 97a5992) and matches the
trimmed line with ``find()`` of ``^...$`` (``regex/RegexComposed.java:112-118``;
``command/SingleLineCommand2.java:102``, ``command/CommandMultilines2.java:98``). The same
is done here, with Java's semantics: model regexes are Java regexes, so every leaf goes
through ``tools.model.java_regex.to_python`` (ASCII ``\\d \\w \\s \\b`` and POSIX classes,
line-bounded ``.``, ASCII-only case folding; see the guide's "Regex semantics" section).
``{regex, ci: true}`` and ``{literal, ci}`` leaves fold ASCII case; absent ``ci`` means
case sensitive. The finished pattern gets Java's implicit ``$``: one final line
terminator may follow the match (``line_pattern``).
"""

from __future__ import annotations

import json
from functools import cache
from typing import Any

import regex

from tools.model import Part
from tools.model.java_regex import line_pattern, literal_to_python, to_python

FLAGS = 0
LIST_JOINERS = {"seq": "", "alt": "|"}
QUANTIFIERS = {"opt": "?", "star": "*", "plus": "+"}


class PartError(ValueError):
    """A Part that is neither a known form nor free of unresolved ``ref``."""


def part_to_regex(part: Part) -> str:
    """Translate a resolved Part to a regex source string (no anchors added)."""
    for key, joiner in LIST_JOINERS.items():
        if key in part:
            return "(?:" + joiner.join(part_to_regex(p) for p in part[key]) + ")"
    for key, quantifier in QUANTIFIERS.items():
        if key in part:
            return "(?:" + part_to_regex(part[key]) + ")" + quantifier
    if "regex" in part:
        return "(?:" + to_python(str(part["regex"]), ci=bool(part.get("ci"))) + ")"
    if "literal" in part:
        return "(?:" + literal_to_python(str(part["literal"]), ci=bool(part.get("ci"))) + ")"
    raise PartError(f"unresolved or unknown Part: {sorted(part)}")


def part_key(part: Part) -> str:
    """A stable cache key for a Part."""
    return json.dumps(part, sort_keys=True, separators=(",", ":"))


@cache
def _compile_source(source: str) -> Any:
    return regex.compile(source, FLAGS)


@cache
def _compile_key(key: str) -> Any:
    return _compile_source(line_pattern(part_to_regex(json.loads(key))))


def compile_part(part: Part) -> Any:
    """Compile (memoized per distinct Part) a pattern for ``fullmatch`` on a line."""
    return _compile_key(part_key(part))
