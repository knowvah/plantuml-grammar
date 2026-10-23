"""``extracted/gantt-lang.json`` to the variables of ``model/generated/gantt-lang.yaml``.

The nine ``NaturalGanttCommand`` sentences have no regex of their own: a sentence is the
composition subject x verb phrase (``gantt/command/NaturalGanttCommand.java:74-141``).
This module turns each subject, verb, "ignored" filler and complement tree into one
variable, named from the upstream class (``SubjectTask`` -> ``SUBJECT_TASK``,
``ComplementDate`` with ``type=ANY`` -> ``COMPLEMENT_DATE_ANY``, verb ``isColored`` ->
``VERB_IS_COLORED``) and returns the header notes that tell the hand-written sentence
grammar how to combine them.
"""

from __future__ import annotations

import re
import textwrap
from collections.abc import Mapping, Sequence
from typing import Any

from tools.model import Part
from tools.translate.ubrex import translate_tree

Doc = Mapping[str, Any]
SPACES_VAR = "SPACES"
AND_VAR = "AND"
VERB_PREFIX = "VERB_"
IGNORED_PREFIX = "IGNORED_"
WRAP = 96
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON_IDENT = re.compile(r"[^A-Z0-9]+")


def upper_snake(name: str) -> str:
    """``SubjectTask`` -> ``SUBJECT_TASK``; ``isOrAre`` -> ``IS_OR_ARE``."""
    return _NON_IDENT.sub("_", _CAMEL.sub("_", name).upper()).strip("_")


def simple_name(fqcn: str) -> str:
    """Last dotted segment of a class name."""
    return fqcn.rsplit(".", 1)[-1]


def complement_names(complements: Sequence[Doc]) -> list[str]:
    """Variable names, one per complement (class, plus its ``params`` values if any)."""
    names = []
    for item in complements:
        suffix = "".join("_" + upper_snake(str(v)) for _, v in sorted(item["params"].items()))
        names.append(upper_snake(simple_name(item["class"])) + suffix)
    return names


def _put(variables: dict[str, Part], name: str, part: Part) -> None:
    if name in variables:
        raise ValueError(f"gantt-lang variable name collides: {name}")
    variables[name] = part


def build_variables(doc: Doc, warnings: list[str]) -> tuple[dict[str, Part], dict[str, Any]]:
    """Variables plus the lookup tables (``ignored``: tree key to name) used by the notes."""

    def tr(tree: Doc) -> Part:
        return translate_tree(dict(tree), warnings)

    variables: dict[str, Part] = {}
    _put(variables, SPACES_VAR, tr(doc["combination"]["spaces"]))
    _put(variables, AND_VAR, tr(doc["combination"]["and"]))
    for subject in doc["subjects"]:
        _put(variables, upper_snake(simple_name(subject["class"])), tr(subject["tree"]))
    for verb in doc["verbs"]:
        _put(variables, VERB_PREFIX + upper_snake(verb["name"]), tr(verb["tree"]))
    names = complement_names(doc["complements"])
    for name, item in zip(names, doc["complements"], strict=True):
        _put(variables, name, tr(item["tree"]))
    ignored = ignored_names(doc, tr, variables)
    return variables, {"complements": names, "ignored": ignored}


def ignored_names(doc: Doc, tr: Any, variables: dict[str, Part]) -> dict[str, str]:
    """Name each distinct "ignored" filler ``IGNORED_<n>`` in order of first use."""
    names: dict[str, str] = {}
    for subject in doc["subjects"]:
        for phrase in subject["verbPhrases"]:
            tree = phrase["ignored"]
            key = repr(tree)
            if tree is not None and key not in names:
                names[key] = f"{IGNORED_PREFIX}{len(names) + 1}"
                _put(variables, names[key], tr(tree))
    return names


def sentence_notes(doc: Doc, lookup: Mapping[str, Any]) -> list[str]:
    """Header lines: how a sentence is composed from the variables, then the full table."""
    notes = [
        "Variables of the Gantt natural-language sentence grammar (not a command regex).",
        "Upstream composition (gantt-lang.json `combination.rule`, "
        "gantt/command/NaturalGanttCommand.java:74-141):",
        *textwrap.wrap(
            doc["combination"]["rule"], width=WRAP, initial_indent="  ", subsequent_indent="    "
        ),
        "As model parts, with the variables below:",
        f"  sentence    = seq[ opt({SPACES_VAR}), <SUBJECT_*>, opt({SPACES_VAR}), "
        f"phrase, star(seq[ {AND_VAR}, phrase ]) ]",
        f"  phrase      = seq[ <VERB_*>, opt({SPACES_VAR}), opt(seq[ <IGNORED_n>, "
        f"opt({SPACES_VAR}) ]), <COMPLEMENT_*> ]  (IGNORED only where listed below)",
        "  phrase set  = alt of the subject's phrases below, in listed order; UBrex takes the "
        "first whose verb+ignored+complement matches",
        "                (committed: no backtracking into a later phrase), and after "
        f"`{AND_VAR}` the next phrase is chosen from the same list again.",
        f"  {SPACES_VAR} is one or more spaces, so opt({SPACES_VAR}) is zero or more.",
        "Subjects (command order) and their phrases, as `verb [ignored] complement`:",
    ]
    for subject in doc["subjects"]:
        title = upper_snake(simple_name(subject["class"]))
        notes.append(f"  {title} (commandOrder {subject['commandOrder']}):")
        for phrase in subject["verbPhrases"]:
            filler = lookup["ignored"].get(repr(phrase["ignored"]), "-")
            comp = lookup["complements"][phrase["complement"]]
            verb = VERB_PREFIX + upper_snake(phrase["verb"])
            notes.append(f"    {phrase['order']:>2}: {verb} [{filler}] {comp}")
    unreferenced = [simple_name(u["class"]) for u in doc.get("unreferenced", [])]
    if unreferenced:
        notes.append(f"Instantiated but referenced by no phrase: {', '.join(unreferenced)}")
    return notes
