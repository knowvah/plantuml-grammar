"""UBrex Challenge tree (contract I1 ``ub-*`` nodes) to regex source.

UBrex (``com/plantuml/ubrex``, pinned 97a5992) is a hand-rolled matcher, not a regex
engine, and it never backtracks: every Challenge returns one match length and the parent
carries on from there (``CompositeList.java:100-115``). ``regex_of`` produces the regex
that accepts the same text, using look-ahead where UBrex consults the text without
consuming it. Where a plain regex would be more permissive (a quantifier or alternative
that UBrex commits to), the translator records ``semantics:committed-match``.

Case: UBrex folds ASCII ``A-Z`` only, in both the stored pattern and the input
(``ChallengeSingleChar.java:39`` constant ``CASE_INSENSITIVE``, ``:61-62`` pattern
lowercased, ``:78-79`` input lowercased; ``CharSet.java:39,45,103-104`` the same for sets;
``CaseMode.java:41`` the fold is ASCII-only). Every leaf therefore carries
``caseMode``; ``Ctx.ci`` is the case mode of the enclosing regex Part and a leaf whose mode
differs is scoped with ``(?i:...)`` / ``(?-i:...)``. Char classes have no case mode.

Residual inexactness: regex ``ci`` folds Unicode (``K`` U+212A matches ``k``) where UBrex
folds ASCII only; ``[\\s\\S]`` stands for ``ANY`` (UBrex ANY also matches ``\\n``); control
characters below 32 index ``CharSet`` bits ``c+64`` through a negative shift
(``CharSet.java:106-112``), which a regex cannot express (command lines never contain them).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

Node = dict[str, Any]
Handler = Callable[[Node, "Ctx"], str]
Width = tuple[int, int | None]

PREFIX = "ub-"
CASE_INSENSITIVE = "CASE_INSENSITIVE"
KEY_CASE = "caseMode"
WARN_VARIABLE_LOOKBEHIND = "portability:variable-width-lookbehind"
ANYTHING = "[\\s\\S]"
NOTHING = "(?!)"

# Meta characters outside / inside a bracket class (also `&`, `~`, `|` which some engines
# treat as set operators, and `-`).
_META = frozenset("\\.^$|?*+()[]{}")
_CLASS_META = frozenset("\\]^-[&~|")
_MIN_RANGE = 3  # shorter runs read better as plain members
_CTRL_LIMIT = 0x20
_DEL = 0x7F
# One regex atom that needs no `(?:...)` before a quantifier: escape, bracket class, char.
_SINGLE_ATOM = re.compile(r"\\.|\[(?:\\.|[^\]\\])*\]|[^\\\[\]()|*+?{}.^$]", re.DOTALL)

# CharClassRaw (CharClassRaw.java), as bracket-class members.
CLASS_BODY: dict[str, str] = {
    "ANY": "\\s\\S",  # CharClassRaw.java:41
    "SPACE": " ",  # :47
    "GUILLEMET": '"\u201c\u201d',  # :53
    "WORD": "a-zA-Z0-9_",  # :59
    "DIGIT": "0-9_",  # :65
    "ALPHA_NUMERIC": "\\p{L}\\p{Nd}",  # :71 Character.isLetterOrDigit
    "LETTER": "\\p{L}",  # :77 Character.isLetter
}


@dataclass(frozen=True)
class Ctx:
    """Rendering context: enclosing case mode, direction and the warning collector."""

    ci: bool
    rev: bool = False
    warnings: list[str] = field(default_factory=list, compare=False)


def is_ci(node: Node) -> bool:
    """True when the leaf's ``caseMode`` is ``CASE_INSENSITIVE``."""
    return bool(node.get(KEY_CASE) == CASE_INSENSITIVE)


def tree_ci(node: Node) -> bool:
    """True when any leaf under ``node`` folds case (the enclosing Part then carries ``ci``)."""
    return is_ci(node) or any(tree_ci(c) for c in node["children"])


def escape(char: str) -> str:
    """One literal character outside a bracket class."""
    return "\\" + char if char in _META else _printable(char)


def _printable(char: str) -> str:
    code = ord(char)
    return f"\\x{code:02x}" if code < _CTRL_LIMIT or code == _DEL else char


def _class_char(char: str) -> str:
    return "\\" + char if char in _CLASS_META else _printable(char)


def class_members(chars: str) -> str:
    """Bracket-class members for ``chars``; runs of three or more become ranges."""
    codes = sorted({ord(c) for c in chars})
    out: list[str] = []
    i = 0
    while i < len(codes):
        j = i
        while j + 1 < len(codes) and codes[j + 1] == codes[j] + 1:
            j += 1
        first, last = chr(codes[i]), chr(codes[j])
        if j - i + 1 >= _MIN_RANGE:
            out.append(f"{_class_char(first)}-{_class_char(last)}")
        else:
            out.extend(_class_char(chr(c)) for c in codes[i : j + 1])
        i = j + 1
    return "".join(out)


def _scoped(rx: str, leaf_ci: bool, ctx: Ctx) -> str:
    if leaf_ci == ctx.ci:
        return rx
    return f"(?{'i' if leaf_ci else '-i'}:{rx})"


def _atom(rx: str) -> str:
    return rx if _SINGLE_ATOM.fullmatch(rx) else f"(?:{rx})"


def regex_of(node: Node, ctx: Ctx) -> str:
    """Regex source for ``node``; raises ``ValueError`` for an unknown ``ub-*`` type."""
    handler = HANDLERS.get(node["t"])
    if handler is None:
        raise ValueError(f"unsupported UBrex node type {node['t']!r}")
    return handler(node, ctx)


def width_of(node: Node) -> Width:
    """``(min, max)`` characters matched by ``node``; ``max`` is None when unbounded."""
    return WIDTHS[node["t"]](node)


def _sub(node: Node, ctx: Ctx) -> str:
    return regex_of(node["children"][0], ctx)


def _concat(children: list[Node], ctx: Ctx) -> str:
    ordered = reversed(children) if ctx.rev else children
    return "".join(regex_of(c, ctx) for c in ordered)


# ---- leaves ---------------------------------------------------------------------------


def single_char(node: Node, ctx: Ctx) -> str:
    """ChallengeSingleChar.java:74-84 (compares the lowercased input char)."""
    return _scoped(escape(node["pattern"]), is_ci(node), ctx)


def char_class(node: Node, ctx: Ctx) -> str:
    """ChallengeCharClass.java:51-58; negation from CharClass.java:47-55."""
    caret = "^" if node["negated"] else ""
    return f"[{caret}{CLASS_BODY[node['charClass']]}]"


def char_set(node: Node, ctx: Ctx) -> str:
    """ChallengeCharSet.java:95-103: ``(contains or class) != reversed``."""
    body = class_members(node["chars"]) + "".join(CLASS_BODY[c] for c in node["classes"])
    if not body:
        rx = ANYTHING if node["negated"] else NOTHING
    else:
        rx = f"[{'^' if node['negated'] else ''}{body}]"
    return _scoped(rx, is_ci(node), ctx)


def end_of_text(node: Node, ctx: Ctx) -> str:
    """ChallengeEndOfText.java:40-44 (position >= length)."""
    return "$"


# ---- composites -----------------------------------------------------------------------


def composite_list(node: Node, ctx: Ctx) -> str:
    """CompositeList.java:100-115 (sequence; matched backwards inside a look-behind)."""
    return _concat(node["children"], ctx)


def composite_named(node: Node, ctx: Ctx) -> str:
    """CompositeNamed.java:61-80 (a sequence whose text is captured under ``name``)."""
    return _concat(node["children"], ctx)


def alternative(node: Node, ctx: Ctx) -> str:
    """ChallengeAlternative.java:50-58 (first alternative that matches wins)."""
    branches = [regex_of(c, ctx) for c in node["children"]]
    return branches[0] if len(branches) == 1 else "(?:" + "|".join(branches) + ")"


def _quantified(node: Node, ctx: Ctx, suffix: str) -> str:
    return _atom(_sub(node, ctx)) + suffix


def optional(node: Node, ctx: Ctx) -> str:
    """ChallengeOptional.java:52-57."""
    return _quantified(node, ctx, "?")


def zero_or_more(node: Node, ctx: Ctx) -> str:
    """ChallengeZeroOrMore.java:51-64 (greedy, no give-back)."""
    return _quantified(node, ctx, "*")


def one_or_more(node: Node, ctx: Ctx) -> str:
    """ChallengeOneOrMore.java:52-68 (greedy, no give-back)."""
    return _quantified(node, ctx, "+")


def _runs(counts: list[int]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for value in sorted({c for c in counts if c > 0}):
        if runs and runs[-1][1] == value - 1:
            runs[-1] = (runs[-1][0], value)
        else:
            runs.append((value, value))
    return runs


def repetition(node: Node, ctx: Ctx) -> str:
    """ChallengeRepetition.java:48-70 with Repetition.java:93-97.

    UBrex consumes the maximal run of the origin and then requires the run length to be one
    of ``counts`` or at least ``min``; ``(?!X)`` after each bounded run reproduces that.
    """
    inner = _sub(node, ctx)
    branches = [
        f"(?:{inner}){{{lo if lo == hi else f'{lo},{hi}'}}}(?!{inner})"
        for lo, hi in _runs(node["counts"])
    ]
    if node["min"] is not None:
        branches.append(f"(?:{inner}){{{node['min']},}}")
    if not branches:
        return NOTHING
    return branches[0] if len(branches) == 1 else "(?:" + "|".join(branches) + ")"


def up_to(node: Node, ctx: Ctx) -> str:
    """ChallengeUpTo.java:46-56: skip characters until the origin matches (not consumed)."""
    stop = _sub(node, ctx)
    return f"(?:(?!{stop}){ANYTHING})*(?={stop})"


def lazy_one_or_more(node: Node, ctx: Ctx) -> str:
    """ChallengeLazzyOneOrMore.java:48-69 (stop condition peeked, not consumed).

    ChallengeOneOrMoreUpToOldVersion.java:48-67 has the same observable behaviour.
    """
    origin, stop = (regex_of(c, ctx) for c in node["children"][:2])
    return f"{origin}(?:(?!{stop}){_atom(origin)})*(?={stop})"


def _look(prefix: str, inner: str) -> str:
    return f"(?{prefix}{inner})"


def look_ahead(node: Node, ctx: Ctx) -> str:
    """ChallengeLookAhead.java:53-67."""
    return _look("!" if node["negated"] else "=", _sub(node, ctx))


def look_behind(node: Node, ctx: Ctx) -> str:
    """ChallengeLookBehind.java:48-63: origin runs on the reversed text.

    The origin is rendered in reverse order. A variable-width origin cannot be a portable
    regex look-behind, so it is dropped and recorded in ``ctx.warnings``.
    """
    low, high = width_of(node["children"][0])
    if low != high:
        ctx.warnings.append(WARN_VARIABLE_LOOKBEHIND)
        return ""
    inner = _sub(node, replace(ctx, rev=not ctx.rev))
    return _look("<!" if node["negated"] else "<=", inner)


# ---- widths ---------------------------------------------------------------------------


def _one(node: Node) -> Width:
    return (1, 1)


def _zero(node: Node) -> Width:
    return (0, 0)


def _sum(node: Node) -> Width:
    widths = [width_of(c) for c in node["children"]]
    high = None if any(h is None for _, h in widths) else sum(h or 0 for _, h in widths)
    return (sum(low for low, _ in widths), high)


def _alternatives(node: Node) -> Width:
    widths = [width_of(c) for c in node["children"]]
    highs = [h for _, h in widths]
    return (min(low for low, _ in widths), None if None in highs else max(h or 0 for h in highs))


def _optional(node: Node) -> Width:
    return (0, width_of(node["children"][0])[1])


def _star(node: Node) -> Width:
    return (0, None)


def _plus(node: Node) -> Width:
    return (width_of(node["children"][0])[0], None)


def _repetition(node: Node) -> Width:
    low, high = width_of(node["children"][0])
    counts = [c for c in node["counts"] if c > 0]
    if node["min"] is not None:
        counts.append(node["min"])
    if not counts:
        return (0, 0)
    unbounded = node["min"] is not None or high is None
    return (low * min(counts), None if unbounded else high * max(counts))


def _scan(node: Node) -> Width:
    return (0, None)


def _lazy(node: Node) -> Width:
    return (width_of(node["children"][0])[0], None)


HANDLERS: dict[str, Handler] = {
    PREFIX + "ChallengeSingleChar": single_char,
    PREFIX + "ChallengeCharClass": char_class,
    PREFIX + "ChallengeCharSet": char_set,
    PREFIX + "ChallengeEndOfText": end_of_text,
    PREFIX + "CompositeList": composite_list,
    PREFIX + "CompositeNamed": composite_named,
    PREFIX + "ChallengeAlternative": alternative,
    PREFIX + "ChallengeOptional": optional,
    PREFIX + "ChallengeZeroOrMore": zero_or_more,
    PREFIX + "ChallengeOneOrMore": one_or_more,
    PREFIX + "ChallengeRepetition": repetition,
    PREFIX + "ChallengeUpTo": up_to,
    PREFIX + "ChallengeLazzyOneOrMore": lazy_one_or_more,
    PREFIX + "ChallengeOneOrMoreUpToOldVersion": lazy_one_or_more,
    PREFIX + "ChallengeLookAhead": look_ahead,
    PREFIX + "ChallengeLookBehind": look_behind,
}

WIDTHS: dict[str, Callable[[Node], Width]] = {
    PREFIX + "ChallengeSingleChar": _one,
    PREFIX + "ChallengeCharClass": _one,
    PREFIX + "ChallengeCharSet": _one,
    PREFIX + "ChallengeEndOfText": _zero,
    PREFIX + "CompositeList": _sum,
    PREFIX + "CompositeNamed": _sum,
    PREFIX + "ChallengeAlternative": _alternatives,
    PREFIX + "ChallengeOptional": _optional,
    PREFIX + "ChallengeZeroOrMore": _star,
    PREFIX + "ChallengeOneOrMore": _plus,
    PREFIX + "ChallengeRepetition": _repetition,
    PREFIX + "ChallengeUpTo": _scan,
    PREFIX + "ChallengeLazzyOneOrMore": _lazy,
    PREFIX + "ChallengeOneOrMoreUpToOldVersion": _lazy,
    PREFIX + "ChallengeLookAhead": _zero,
    PREFIX + "ChallengeLookBehind": _zero,
}

# Where each type's matching rule lives at 97a5992 (`com/plantuml/ubrex/<file>:<line>`).
CITATIONS: dict[str, str] = {
    PREFIX + "ChallengeSingleChar": "ChallengeSingleChar.java:74",
    PREFIX + "ChallengeCharClass": "ChallengeCharClass.java:51",
    PREFIX + "ChallengeCharSet": "ChallengeCharSet.java:95",
    PREFIX + "ChallengeEndOfText": "ChallengeEndOfText.java:40",
    PREFIX + "CompositeList": "CompositeList.java:100",
    PREFIX + "CompositeNamed": "CompositeNamed.java:61",
    PREFIX + "ChallengeAlternative": "ChallengeAlternative.java:50",
    PREFIX + "ChallengeOptional": "ChallengeOptional.java:52",
    PREFIX + "ChallengeZeroOrMore": "ChallengeZeroOrMore.java:51",
    PREFIX + "ChallengeOneOrMore": "ChallengeOneOrMore.java:52",
    PREFIX + "ChallengeRepetition": "ChallengeRepetition.java:48",
    PREFIX + "ChallengeUpTo": "ChallengeUpTo.java:46",
    PREFIX + "ChallengeLazzyOneOrMore": "ChallengeLazzyOneOrMore.java:48",
    PREFIX + "ChallengeOneOrMoreUpToOldVersion": "ChallengeOneOrMoreUpToOldVersion.java:48",
    PREFIX + "ChallengeLookAhead": "ChallengeLookAhead.java:53",
    PREFIX + "ChallengeLookBehind": "ChallengeLookBehind.java:48",
}
