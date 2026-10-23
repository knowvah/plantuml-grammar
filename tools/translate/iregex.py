"""IRegex tree (contract I1 ``Node``) to model Part (contract I2).

Case-insensitivity: every ``Pattern2`` is compiled with ``Pattern.CASE_INSENSITIVE``
(``regex/Pattern2.java:114``), and ``RegexConcat.build`` adds no flags of its own
(``regex/RegexConcat.java:94-117``), so every translated literal carries ``ci: true``.

Anchors: ``RegexConcat.build`` asserts that the first partial is ``RegexLeaf.start()``
(``^``) and the last ``RegexLeaf.end()`` (``$``) (``RegexConcat.java:114-115``), so a
command always matches a whole line. Those two leaves are implicit in the model and
dropped; anchors embedded inside a larger leaf pattern are kept verbatim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from tools.model import Part
from tools.translate.macros import portability_issues, portable

Node = dict[str, Any]

START_ANCHOR = "^"
END_ANCHOR = "$"
KIND_MULTILINE = "multiline"
KIND_OPAQUE = "opaque"
WARN_DROPPED_NAME = "dropped-node-name"
KEY_MAX_LINES = "nbMaxLines"
# Opaque factories compiled with plain java.util.regex.Pattern (case-sensitive), not
# Pattern2: PSystemColorsFactory.java:48, PSystemDitaaFactory.java:123,
# PSystemDotFactory.java:48. PSystemSudokuFactory uses Pattern2 (case-insensitive).
CASE_SENSITIVE_CLASSES = frozenset(
    {
        "net.sourceforge.plantuml.eggs.PSystemColorsFactory",
        "net.sourceforge.plantuml.ditaa.PSystemDitaaFactory",
        "net.sourceforge.plantuml.directdot.PSystemDotFactory",
    }
)

# Plain text that needs no regex escaping; `%` is excluded (macro introducer).
_LITERAL_CHAR = r"[^\\\[\]().*+?{}|^$%]"
_LITERAL = re.compile(rf"(?:{_LITERAL_CHAR}|\\[^A-Za-z0-9])+")
_UNESCAPE = re.compile(r"\\(.)")
_WRAPPED = re.compile(r"\((?:\?:)?(.*)\)([?*+]?)", re.DOTALL)
_QUANTIFIER_KEY = {"?": "opt", "*": "star", "+": "plus"}
_UNARY = {"opt", "star", "plus"}


@dataclass(frozen=True)
class Translated:
    """Result of translating one command; ``end`` is None for single-line kinds."""

    kind: str
    parts: Part
    end: Part | None
    warnings: tuple[str, ...]
    join_max_lines: int | None = None


def _split_alternatives(body: str) -> list[str] | None:
    """Split ``body`` on top-level ``|``; None when parentheses are unbalanced."""
    depth, in_class, i, start = 0, False, 0, 0
    pieces: list[str] = []
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            i += 1
        elif in_class:
            in_class = ch != "]"
        elif ch == "[":
            in_class = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return None
        elif ch == "|" and depth == 0:
            pieces.append(body[start:i])
            start = i + 1
        i += 1
    pieces.append(body[start:])
    return pieces if depth == 0 and not in_class else None


def _branch(text: str) -> Part:
    """One alternative: a ci literal when it is plain text, else an expanded regex."""
    if text and _LITERAL.fullmatch(text):
        return {"literal": _UNESCAPE.sub(r"\1", text), "ci": True}
    return {"regex": portable(text), "ci": True}


def _wrapped_body(pattern: str) -> tuple[str, str] | None:
    """``(body, quantifier)`` when one group spans the whole pattern, else None."""
    match = _WRAPPED.fullmatch(pattern)
    if match is None:
        return None
    inner = match.group(1)
    if inner.startswith("?"):  # lookaround, inline flags, named groups: not a plain group
        return None
    # `(a)(b)` also matches the wrapper regex; the inner text must be balanced.
    if _split_alternatives(inner) is None:
        return None
    return inner, match.group(2)


def _literal_part(pattern: str) -> Part | None:
    """Alt of ci literals/regex branches for an unnamed literal-alternation leaf."""
    wrapped = _wrapped_body(pattern)
    body, quantifier = wrapped if wrapped else (pattern, "")
    branches = _split_alternatives(body)
    if branches is None or not any(_LITERAL.fullmatch(b) for b in branches):
        return None
    parts = [_branch(b) for b in branches]
    part: Part = parts[0] if len(parts) == 1 else {"alt": parts}
    return {_QUANTIFIER_KEY[quantifier]: part} if quantifier else part


def leaf_to_part(pattern: str, name: str | None) -> Part:
    """Translate a leaf. Named leaves stay regexes so the Part keeps the ``name``."""
    if name is None:
        part = _literal_part(pattern)
        if part is not None:
            return part
    part = {"regex": portable(pattern), "ci": True}
    if name is not None:
        part["name"] = name
    return part


def _is_anchor(node: Node, anchor: str) -> bool:
    return node["t"] == "leaf" and node["pattern"] == anchor


def _children(node: Node, warnings: list[str]) -> list[Part]:
    return [translate_node(c, warnings) for c in node["children"]]


def _group(parts: list[Part], key: str) -> Part:
    if len(parts) == 1 and key == "seq":
        return parts[0]
    return {key: parts}


def translate_node(node: Node, warnings: list[str]) -> Part:
    """Translate one Node; anchors are handled by ``translate_tree`` only."""
    kind = node["t"]
    if kind == "leaf":
        return leaf_to_part(node["pattern"], node["name"])
    if node["name"]:
        warnings.append(f"{WARN_DROPPED_NAME}:{node['name']}")
    children = _children(node, warnings)
    if kind == "concat":
        return _group(children, "seq")
    if kind == "or":
        return {"alt": children}
    if kind in _UNARY:
        return {kind: _group(children, "seq")}
    raise ValueError(f"unsupported IRegex node type {kind!r}")


def translate_tree(node: Node, warnings: list[str]) -> Part:
    """Translate a command's start/end tree, dropping the implicit outer anchors."""
    if node["t"] == "concat":
        kids = list(node["children"])
        if kids and _is_anchor(kids[0], START_ANCHOR):
            kids = kids[1:]
        if kids and _is_anchor(kids[-1], END_ANCHOR):
            kids = kids[:-1]
        if len(kids) != len(node["children"]):
            node = {**node, "children": kids}
            if not kids:
                return {"regex": "", "ci": True}
    return translate_node(node, warnings)


def _regexes(part: Part) -> list[str]:
    found = [part["regex"]] if "regex" in part else []
    for key in ("seq", "alt"):
        for child in part.get(key, []):
            found.extend(_regexes(child))
    for key in _UNARY:
        if key in part:
            found.extend(_regexes(part[key]))
    return found


def _strip_ci(part: Part) -> Part:
    """Copy of ``part`` with every regex ``ci`` flag removed (case-sensitive upstream)."""
    out = {k: v for k, v in part.items() if k != "ci" or "literal" in part}
    for key in ("seq", "alt"):
        if key in out:
            out[key] = [_strip_ci(c) for c in out[key]]
    for key in _UNARY:
        if key in out:
            out[key] = _strip_ci(out[key])
    return out


def translate_command(command: dict[str, Any]) -> Translated:
    """Translate one I1 command with ``engine: IRegex`` to kind/parts/end/warnings.

    Regex Parts carry ``ci: true`` (``Pattern2.java:114``) except for the classes in
    ``CASE_SENSITIVE_CLASSES``. A command with ``nbMaxLines`` (``CommandDecoratorMultine``)
    and no end tree yields ``join_max_lines`` instead of an ``end``.
    """
    warnings: list[str] = []
    parts = translate_tree(command["start"], warnings)
    end = translate_tree(command["end"], warnings) if command["end"] else None
    if command["class"] in CASE_SENSITIVE_CLASSES:
        parts = _strip_ci(parts)
    for tree in (parts, end):
        for pattern in _regexes(tree) if tree else []:
            warnings.extend(f"portability:{i}" for i in portability_issues(pattern))
    join = command.get(KEY_MAX_LINES) if end is None and command["kind"] == KIND_MULTILINE else None
    return Translated(command["kind"], parts, end, tuple(sorted(set(warnings))), join)
