"""Prefix-closure regexes for ``join`` commands (decision D4, contract C4).

``tools.interp.scan.scan_join`` joins lines with U+E100 and stops as soon as
``regex.fullmatch(text + JOINER, partial=True)`` says no longer join can match
(``tools/interp/scan.py:137-153``). JavaScript has no partial matching, so the TS scanner
tests ``joined + JOINER`` against the pattern built here and stops only when it rejects.

``prefix_pattern(part)`` returns a whole-line source (``line_pattern_js`` of the body, flag
``u``) that accepts every string that can still be extended to a match of ``part``.

Soundness. The scanner stops only on a rejection, so the pattern may accept too much (the
scan then runs a little longer; verdicts are unchanged) but must never reject a string
that Python's partial match accepts. Every approximation therefore *widens* the language,
for the prefix positions and for the complete sub-parts alike. The prefix of ``a b c`` is
``p(a) | a p(b) | a b p(c)``, so each complete sub-part ``a`` or ``b`` is itself a
sub-expression that may be followed by more pattern, and it is built from a *widened* leaf:

* lookarounds are dropped (they only constrain; a lookahead may also look past the cut
  point into text the prefix has not seen yet). One quirk is kept on purpose: ``regex``
  reports a partial match as soon as the text ends *while a lookahead is still reading*,
  whatever the rest of the pattern would need. So a lookahead ``(?=X)`` / ``(?!X)`` also
  contributes ``p(X)`` at its position: ``a (?=X) b`` has prefixes ``p(a) | a p(X) | a p(b)``
  (the ``EbnfRuleMultilines`` join starts with such a lookahead);
* anchors and word boundaries (``^ $ \\A \\Z \\z \\G \\b \\B``) are dropped, for the same reason;
* back references (``\\1``, ``\\k<n>``, ``(?P=n)``) become ``[^]*``: a back reference
  consumes text, so "empty" would narrow it, and it may name a group of another sub-part;
* atomic groups ``(?>X)`` and possessive quantifiers: atomicity can only reject strings,
  but removing it is not usable (neighbouring unbounded tokens then split in exponentially
  many ways; the style sheet join hangs Node). So an atomic group or possessive atom whose
  body was translated *exactly* (nothing in it dropped or widened) keeps its emulation
  ``(?=(?<_aN>X))\\k<_aN>`` in complete positions: its first match is the one Python's
  engine commits to on the same text, so keeping it cannot reject what Python accepts.
  A body that had a lookaround, anchor or back reference dropped would reorder the
  engine's choices and commit to a different match, and widening it to a plain group is
  the exponential case, so such a group becomes ``[^]*`` (every string it could match).
  The emulation names are numbered afresh over the finished pattern, since sub-parts repeat;
* named and numbered groups become non-capturing (no back reference survives);
* a leaf that cannot be parsed or translated (recursion ``(?&n)``, ``(?(DEFINE)``,
  conditionals ``(?(``, nested classes, ``\\Q..\\E``, ...) is ``[^]*``, the top of the
  lattice, and so is any quantified or following context that would swallow it.

Quantified ``X`` contributes ``X* p(X)`` (also for ``{n,m}``); the empty string is always
a prefix. ``p`` of a sequence is factored from the right, ``p(a rest) = p(a) | a p(rest)``,
so each complete sub-part appears once per level instead of once per position.

A pattern larger than ``MAX_PATTERN_BYTES`` falls back to ``^[^]*$`` and is logged.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import cache

from tools.model import Part
from tools.model.java_regex import (
    _GROUP,
    _PROPERTY,
    _apply_flags,
    _hex_escape,
)
from tools.model.java_regex_js import (
    _parse_class,
    line_pattern_js,
    literal_to_js,
    to_js,
)

LOGGER = logging.getLogger(__name__)
MAX_PATTERN_BYTES = 64 * 1024
ANY = "[^]*"
TOP_PATTERN = "^[^]*$"
ATOMIC_OPEN = "(?>"
LAZY = "?"
POSSESSIVE = "+"
ATOM_OPEN = "(?=(?<_a@o>"
ATOM_CLOSE = "))\\k<_a@c>"
LOOKAHEADS = frozenset({"(?=", "(?!"})
LOOKBEHINDS = frozenset({"(?<=", "(?<!"})
ZERO_WIDTH_ESCAPES = frozenset("bBAZzG")
QUANTIFIER_CHARS = "*+?"
SUFFIX_CHARS = "?+"
DISTRIBUTE_MAX = 80
REPEAT_QUANTIFIERS = {"opt": "?", "star": "*", "plus": "+"}
BACKREF_PREFIX = "(?P="
_REPEAT = re.compile(r"\{(\d+)(?:,(\d*))?\}")
_ATOM_NAME = re.compile(r"_a@([oc])")
_BACKREF_NAME = re.compile(r"\\k<\w+>")


class PrefixError(ValueError):
    """A Part or regex the prefix builder cannot analyse."""


@dataclass(frozen=True)
class Empty:
    """Matches the empty string only."""


@dataclass(frozen=True)
class Anything:
    """Matches any string (a widened back reference)."""


@dataclass(frozen=True)
class Atom:
    """One character-sized unit, already translated to JS source."""

    js: str


@dataclass(frozen=True)
class Seq:
    items: tuple[Node, ...]


@dataclass(frozen=True)
class Alt:
    branches: tuple[Node, ...]


@dataclass(frozen=True)
class Rep:
    """``body`` repeated by a JS quantifier (``* + ? {n,m}``, ``?`` suffix when lazy)."""

    body: Node
    quantifier: str


@dataclass(frozen=True)
class Atomic:
    """An exactly translated atomic group: complete form is atomic, prefix form is not."""

    body: Node


@dataclass(frozen=True)
class Look:
    """A lookahead: nothing in the complete form, but see ``_cont`` for the cut inside it."""

    body: Node


Node = Empty | Anything | Atom | Seq | Alt | Rep | Atomic | Look
EMPTY = Empty()
ANYTHING = Anything()


def _group(body: str) -> str:
    return f"(?:{body})"


def _repeat(body: Node, quantifier: str) -> Node:
    """``Rep`` with the degenerate bodies and counts folded away."""
    if isinstance(body, (Empty, Anything)):
        return body
    count = _REPEAT.fullmatch(quantifier.removesuffix(LAZY))
    if count and count.group(1) == "0" and count.group(2) in (None, "0"):
        return EMPTY
    return Rep(body, quantifier)


class _Parser:
    """Recursive descent over a Java regex; ``ci`` is the case mode in effect."""

    def __init__(self, src: str, ci: bool) -> None:
        self.src, self.ci, self.i = src, ci, 0
        self.widened = 0  # constructs dropped or widened so far; unchanged = exact

    def parse(self) -> Node:
        node = self.alternation()
        if self.i < len(self.src):
            raise PrefixError("unbalanced )")
        return node

    def peek(self) -> str:
        return self.src[self.i : self.i + 1]

    def alternation(self) -> Node:
        branches = [self.sequence()]
        while self.peek() == "|":
            self.i += 1
            branches.append(self.sequence())
        return branches[0] if len(branches) == 1 else Alt(tuple(branches))

    def sequence(self) -> Node:
        items: list[Node] = []
        while self.i < len(self.src) and self.src[self.i] not in "|)":
            before = self.widened
            items.append(self.quantified(self.atom(), before))
        return items[0] if len(items) == 1 else Seq(tuple(items))

    def quantified(self, node: Node, widened_before: int) -> Node:
        char = self.peek()
        if char and char in QUANTIFIER_CHARS:
            quantifier, self.i = char, self.i + 1
        elif char == "{":
            found = _REPEAT.match(self.src, self.i)
            if found is None:
                raise PrefixError("illegal repetition")
            quantifier, self.i = found.group(), found.end()
        else:
            return node
        suffix = self.peek() if self.peek() in SUFFIX_CHARS else ""
        self.i += len(suffix)
        if suffix == LAZY:
            return _repeat(node, quantifier + LAZY)
        repeated = _repeat(node, quantifier)
        if suffix != POSSESSIVE or not isinstance(repeated, Rep):
            return repeated
        return Atomic(repeated) if self.widened == widened_before else self.widen(ANYTHING)

    def atom(self) -> Node:
        char = self.src[self.i]
        if char == "(":
            return self.group()
        if char == "[":
            js, self.i = _parse_class(self.src, self.i, self.ci)
            return Atom(js)
        if char == "\\":
            return self.escape()
        if char in "^$":
            return self.dropped(1)
        if char in QUANTIFIER_CHARS or char == "{":
            raise PrefixError(f"dangling quantifier {char!r}")
        self.i += 1
        return Atom(to_js(char, ci=self.ci))

    def escape(self) -> Node:
        src, i = self.src, self.i
        if i + 1 >= len(src):
            raise PrefixError("pattern ends with a backslash")
        char = src[i + 1]
        if char in ZERO_WIDTH_ESCAPES:
            return self.dropped(2)
        if char in "123456789":
            self.i += 2
            while self.peek().isdigit():
                self.i += 1
            return self.widen(ANYTHING)
        named = _BACKREF_NAME.match(src, i)
        if named:
            self.i = named.end()
            return self.widen(ANYTHING)
        return self.escaped_atom()

    def widen(self, node: Node) -> Node:
        """Note that the language was widened here; returns ``node``."""
        self.widened += 1
        return node

    def dropped(self, length: int) -> Node:
        """Skip ``length`` characters of a zero-width construct, which becomes empty."""
        self.i += length
        return self.widen(EMPTY)

    def escaped_atom(self) -> Node:
        """A class or single-character escape, translated on its own."""
        src, i = self.src, self.i
        prop = _PROPERTY.match(src, i) if src[i + 1] in "pP" else None
        hexed = _hex_escape(src, i)
        end = prop.end() if prop else i + (hexed[1] if hexed else 2)
        self.i = end
        return Atom(to_js(src[i:end], ci=self.ci))

    def group(self) -> Node:
        found = _GROUP.match(self.src, self.i)
        if found is None or (found.group() == "(" and self.src.startswith("?", self.i + 1)):
            raise PrefixError("malformed group")
        text, self.i = found.group(), found.end()
        if found.group("flags") is not None:
            return self.flag_group(found.group("flags"), found.group("flag_end"))
        special = self.special_group(found, text)
        if special is not None:
            return special
        before = self.widened
        body = self.body(self.ci)
        if text in LOOKBEHINDS:
            return self.widen(EMPTY)
        if text in LOOKAHEADS:
            return self.widen(Look(body))
        if text != ATOMIC_OPEN:
            return body
        return Atomic(body) if self.widened == before else self.widen(ANYTHING)

    def special_group(self, found: re.Match[str], text: str) -> Node | None:
        """``(?P=n)`` and comments; ``None`` for a group with a body."""
        if found.group("call") is not None:
            if not text.startswith(BACKREF_PREFIX):
                raise PrefixError(f"unsupported group {text}")
            return self.widen(ANYTHING)
        if found.group("comment") is not None:
            return EMPTY
        if found.group("cond") is not None or text == "(?|":
            raise PrefixError(f"unsupported group {text}")
        return None

    def flag_group(self, spec: str, flag_end: str) -> Node:
        """``(?i)`` changes the mode for the rest of the group; ``(?i:...)`` scopes it."""
        if flag_end == ")":
            self.ci = _apply_flags(spec, self.ci)
            return EMPTY
        return self.body(_apply_flags(spec, self.ci))

    def body(self, ci: bool) -> Node:
        """A group body parsed under ``ci``; the enclosing case mode is restored after."""
        outer, self.ci = self.ci, ci
        node = self.alternation()
        if self.peek() != ")":
            raise PrefixError("unclosed group")
        self.i += 1
        self.ci = outer
        return node


def _full(node: Node) -> str:
    """JS source of the widened complete language of ``node``."""
    if isinstance(node, (Empty, Look)):
        return ""
    if isinstance(node, Anything):
        return ANY
    if isinstance(node, Atom):
        return node.js
    if isinstance(node, Seq):
        return "".join(_full(item) for item in node.items)
    if isinstance(node, Alt):
        return _group("|".join(_full(branch) for branch in node.branches))
    if isinstance(node, Atomic):
        return ATOM_OPEN + _full(node.body) + ATOM_CLOSE
    return _group(_full(node.body)) + node.quantifier


def _cont(node: Node, rest: str) -> str:
    """JS source of the prefixes of ``node`` followed by anything ``rest`` accepts.

    ``rest`` is the prefix source of whatever follows ``node`` (``""`` when nothing does);
    it always accepts the empty string, so the result includes the empty string too. The
    continuation is threaded through instead of copying each sub-part per position, which
    keeps the pattern linear in the Part (a node's complete form appears once per level
    of alternation or repetition above it, not once per position).
    """
    if isinstance(node, (Empty, Anything)):
        return rest if isinstance(node, Empty) else ANY
    if isinstance(node, Atom):
        return _group(f"|{node.js}{rest}")
    if isinstance(node, Seq):
        return _seq_cont(node, rest)
    if isinstance(node, Alt):
        return _alt_cont(node, rest)
    if isinstance(node, Atomic):
        return _atomic_cont(node, rest)
    if isinstance(node, Look):
        return _look_cont(node, rest)
    return _rep_cont(node, rest)


def _seq_cont(node: Seq, rest: str) -> str:
    for item in reversed(node.items):
        rest = _cont(item, rest)
    return rest


def _alt_cont(node: Alt, rest: str) -> str:
    """Distribute a short ``rest`` over the branches; otherwise ``p(alt) | alt rest``."""
    if len(rest) <= DISTRIBUTE_MAX:
        return _group("|".join(_cont(branch, rest) for branch in node.branches))
    alone = "|".join(_cont(branch, "") for branch in node.branches)
    return _group(f"{alone}|{_full(node)}{rest}")


def _look_cont(node: Look, rest: str) -> str:
    """The lookahead is dropped, except that Python's partial match also succeeds when the
    text ends while a lookahead is still reading: then the rest of the text is a prefix
    of the lookahead's body, whatever the pattern would match after it."""
    inside = _cont(node.body, "")
    return ANY if inside == ANY else _group(f"{inside}|{rest}")


def _atomic_cont(node: Atomic, rest: str) -> str:
    """A cut inside the group is widened (not atomic); a complete group stays atomic."""
    partial = _cont(node.body, "")
    return ANY if partial == ANY else _group(f"{partial}|{_full(node)}{rest}")


def _rep_cont(node: Rep, rest: str) -> str:
    """``X* (p(X) | rest)``: whole iterations, then a partial one or what follows."""
    partial = _cont(node.body, "")
    if partial == ANY:
        return ANY
    return _group(_group(_full(node.body)) + "*" + _group(f"{partial}|{rest}"))


@cache
def _leaf(regex_source: str, ci: bool) -> Node:
    """The widened AST of a regex leaf; ``Anything`` when it cannot be analysed."""
    try:
        return _Parser(regex_source, ci).parse()
    except (ValueError, RecursionError, IndexError):
        # JsRegexError / JavaRegexError / PrefixError are ValueErrors: an unsupported or
        # unparsable leaf is the top of the lattice, which only widens.
        return ANYTHING


def _to_node(part: Part) -> Node:
    """The Part as an AST over the same node types as a regex leaf."""
    if "seq" in part:
        return Seq(tuple(_to_node(child) for child in part["seq"]))
    if "alt" in part:
        return Alt(tuple(_to_node(child) for child in part["alt"]))
    for key, quantifier in REPEAT_QUANTIFIERS.items():
        if key in part:
            return _repeat(_to_node(part[key]), quantifier)
    ci = bool(part.get("ci"))
    if "regex" in part:
        return _leaf(str(part["regex"]), ci)
    if "literal" in part:
        return Seq(tuple(Atom(literal_to_js(char, ci=ci)) for char in str(part["literal"])))
    raise PrefixError(f"unresolved or unknown Part: {sorted(part)}")


def _number_atomics(source: str) -> str:
    """Give every emulated atomic group its own name; opens and closes nest like parentheses."""
    stack: list[int] = []
    counter = 0

    def name(found: re.Match[str]) -> str:
        nonlocal counter
        if found.group(1) == "o":
            stack.append(counter)
            counter += 1
            return f"_a{stack[-1]}"
        return f"_a{stack.pop()}"

    return _ATOM_NAME.sub(name, source)


def prefix_pattern(part: Part, command: str = "") -> str:
    """Whole-line JS source (flag ``u``) accepting every prefix of a match of ``part``.

    ``command`` only labels the log line when the size guard falls back to ``^[^]*$``.
    Raises ``PrefixError`` for a Part that is not a known form (unresolved ``ref``).
    """
    pattern = line_pattern_js(_number_atomics(_cont(_to_node(part), "")))
    size = len(pattern.encode("utf-8"))
    if size > MAX_PATTERN_BYTES:
        LOGGER.warning(
            "prefix pattern exceeds the size limit; using the top pattern",
            extra={"command": command, "size": size, "limit": MAX_PATTERN_BYTES},
        )
        return TOP_PATTERN
    return pattern


__all__ = ["MAX_PATTERN_BYTES", "TOP_PATTERN", "PrefixError", "prefix_pattern"]
