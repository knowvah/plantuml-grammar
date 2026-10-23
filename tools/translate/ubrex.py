"""UBrex Challenge tree (contract I1 ``ub-*`` nodes) to model Part (contract I2).

``translate_command`` has the same contract as ``iregex.translate_command``. Structure
that the model can express stays structured: ``CompositeList`` becomes ``seq`` (runs of
``ChallengeSingleChar`` merge into one literal), ``ChallengeAlternative`` becomes ``alt``,
``ChallengeOptional``/``ZeroOrMore``/``OneOrMore`` become ``opt``/``star``/``plus``.
Everything else (char classes and sets, bounded repetition, scan-until constructs,
look-around, ``CompositeNamed``) becomes one regex Part built by ``ubrex_regex``; a named
group is a regex Part carrying ``name``.

Matching: ``UBrexSingleLineCommand2.isValid`` requires ``exactMatch()``, i.e. the pattern
consumes the whole trimmed line (``UBrexSingleLineCommand2.java:75-79``,
``UnicodeBracketedExpression.java:73-78``); like IRegex, anchors are implicit, so a
trailing ``ChallengeEndOfText`` is dropped.

Case: ``caseMode`` of each leaf maps to ``ci``; see ``ubrex_regex`` for where UBrex applies
case and the residual differences.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tools.model import Part
from tools.translate.iregex import Translated
from tools.translate.macros import portability_issues
from tools.translate.ubrex_regex import (
    CITATIONS,
    HANDLERS,
    PREFIX,
    Ctx,
    Node,
    is_ci,
    regex_of,
    tree_ci,
)

__all__ = ["CITATIONS", "HANDLERS", "portability_warnings", "translate_command"]

T_LIST = PREFIX + "CompositeList"
T_NAMED = PREFIX + "CompositeNamed"
T_END = PREFIX + "ChallengeEndOfText"
WARN_COMMITTED = "semantics:committed-match"
WARN_FINAL_BRACKET = "semantics:final-bracket"
WARN_PORTABILITY = "portability:"
# Constructs where UBrex commits to its first choice and a regex would backtrack.
_BACKTRACKING = frozenset(
    PREFIX + t for t in ("ChallengeAlternative", "ChallengeOptional", "ChallengeZeroOrMore")
) | {PREFIX + "ChallengeOneOrMore"}
_UNARY_KEYS = {
    PREFIX + "ChallengeOptional": "opt",
    PREFIX + "ChallengeZeroOrMore": "star",
    PREFIX + "ChallengeOneOrMore": "plus",
}
_EMPTY: Part = {"literal": "", "ci": False}

PartHandler = Callable[[Node, list[str]], Part]


def _regex_part(node: Node, warnings: list[str]) -> Part:
    """One regex Part for any node; ``ci`` when a leaf under it folds case."""
    ci = tree_ci(node)
    part: Part = {"regex": regex_of(node, Ctx(ci, warnings=warnings))}
    if ci:
        part["ci"] = True
    if node["t"] == T_NAMED and node["name"]:
        part["name"] = node["name"]
    return part


def _named(node: Node, warnings: list[str]) -> Part:
    """CompositeNamed (CompositeNamed.java:61): a captured group is a named regex Part."""
    return _regex_part(node, warnings)


def _single_char(node: Node, warnings: list[str]) -> Part:
    """ChallengeSingleChar (ChallengeSingleChar.java:74): a literal with its case mode."""
    return {"literal": node["pattern"], "ci": is_ci(node)}


def _items(node: Node, warnings: list[str]) -> list[Part]:
    items: list[Part] = []
    for child in node["children"]:
        if child["t"] == T_LIST:
            items.extend(_items(child, warnings))
        else:
            items.append(translate_node(child, warnings))
    return items


def _merge_literals(items: list[Part]) -> list[Part]:
    merged: list[Part] = []
    for item in items:
        last = merged[-1] if merged else None
        if last is not None and _mergeable(last, item):
            merged[-1] = {"literal": last["literal"] + item["literal"], "ci": item["ci"]}
        else:
            merged.append(item)
    return merged


def _mergeable(left: Part, right: Part) -> bool:
    return (
        "literal" in left
        and "literal" in right
        and left["ci"] == right["ci"]
        and "scope" not in left
    )


def _list(node: Node, warnings: list[str]) -> Part:
    """CompositeList (CompositeList.java:100): a sequence."""
    items = _merge_literals(_items(node, warnings))
    if not items:
        return dict(_EMPTY)
    return items[0] if len(items) == 1 else {"seq": items}


def _alternative(node: Node, warnings: list[str]) -> Part:
    """ChallengeAlternative (ChallengeAlternative.java:50): ordered choice."""
    branches = [translate_node(c, warnings) for c in node["children"]]
    return branches[0] if len(branches) == 1 else {"alt": branches}


def _unary(node: Node, warnings: list[str]) -> Part:
    """Optional / ZeroOrMore / OneOrMore (``ChallengeOptional.java:52``, ``:51``, ``:52``)."""
    return {_UNARY_KEYS[node["t"]]: translate_node(node["children"][0], warnings)}


PART_HANDLERS: dict[str, PartHandler] = {
    PREFIX + "ChallengeSingleChar": _single_char,
    T_LIST: _list,
    T_NAMED: _named,
    PREFIX + "ChallengeAlternative": _alternative,
    **{t: _unary for t in _UNARY_KEYS},
}


def translate_node(node: Node, warnings: list[str]) -> Part:
    """Translate one node; types without a structured form become a regex Part."""
    if node["t"] not in HANDLERS:
        raise ValueError(f"unsupported UBrex node type {node['t']!r}")
    return PART_HANDLERS.get(node["t"], _regex_part)(node, warnings)


def strip_trailing_end(node: Node) -> Node:
    """Drop a final ``ChallengeEndOfText``: the whole line must match anyway."""
    if node["t"] != T_LIST or not node["children"]:
        return node
    kids = list(node["children"])
    if kids[-1]["t"] == T_END:
        kids.pop()
    else:
        kids[-1] = strip_trailing_end(kids[-1])
    return {**node, "children": kids}


def _regexes(part: Part) -> list[str]:
    found = [part["regex"]] if "regex" in part else []
    for key in ("seq", "alt"):
        for child in part.get(key, []):
            found.extend(_regexes(child))
    for key in ("opt", "star", "plus"):
        if key in part:
            found.extend(_regexes(part[key]))
    return found


def portability_warnings(part: Part) -> tuple[str, ...]:
    """``portability:<issue>`` for every regex in ``part`` other engines may reject."""
    issues = {i for rx in _regexes(part) for i in portability_issues(rx)}
    return tuple(sorted(WARN_PORTABILITY + i for i in issues))


def _kinds(node: Node) -> set[str]:
    found = {node["t"]}
    for child in node["children"]:
        found |= _kinds(child)
    return found


def translate_tree(node: Node, warnings: list[str]) -> Part:
    """Translate a command's start or end tree."""
    return translate_node(strip_trailing_end(node), warnings)


def translate_command(command: dict[str, Any]) -> Translated:
    """Translate one I1 command with ``engine: UBrex`` to kind/parts/end/warnings."""
    if command["start"] is None:
        raise ValueError(f"no UBrex start tree for {command['class']}")
    warnings: list[str] = []
    parts = translate_tree(command["start"], warnings)
    end = translate_tree(command["end"], warnings) if command["end"] else None
    trees = [t for t in (command["start"], command["end"]) if t]
    if any(_kinds(t) & _BACKTRACKING for t in trees):
        warnings.append(WARN_COMMITTED)
    if command.get("finalBracket"):
        warnings.append(WARN_FINAL_BRACKET)
    for tree in (parts, end):
        warnings.extend(portability_warnings(tree) if tree else ())
    return Translated(command["kind"], parts, end, tuple(sorted(set(warnings))))
