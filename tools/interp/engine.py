"""The interpreter: run a block through the model the way upstream runs commands.

Upstream semantics mirrored (all at 97a5992):

* Factory loop, ``PSystemBuilder.java:257-287``: factories whose type matches the start
  line are tried in order; the first whose ``createSystem`` returns a non-error diagram
  wins (``isOk``, ``:298-303``). If all fail, ``PSystemErrorUtils.merge``
  (``error/PSystemErrorUtils.java:112-147``) keeps the error with the highest
  ``score()`` (``error/PSystemError.java:382``: ``trace.size() * 10 + ...``, strict ``<``
  so the first factory wins ties). ``trace.size()`` is the number of lines consumed when
  the error arose, so the reported failure is the one that got furthest; ties go to the
  earliest candidate. No candidate at all is ``PSystemUnsupported`` (``:283-284``).
* Command loop, ``command/PSystemCommandFactory.java:107-150``: skip the start line,
  stop at the first ``@end`` line, an empty body (only blank lines / comments) is an
  error at the start line (``:117-122``; ``core/UmlSource.java:255-270``).
* ``getCandidate``, ``PSystemCommandFactory.java:223-247``: commands in list order for
  the current line. ``OK`` consumes one line; ``OK_PARTIAL`` consumes lines until the
  command's end condition (see ``tools.interp.scan``); a multiline command that never
  completes is skipped and the next command is tried. No command matches: syntax error
  at that line (``:169-175``).
* Blank lines: upstream relies on ``CommandNope`` (``command/CommandNope.java:46-58``,
  registered by ``CommonCommands.java:63``). Here a blank line is skipped only when no
  command of the current context matched it, so models that include ``CommandNope``
  behave identically and toy models still accept blank lines. ``'`` and ``/' '/``
  comments are removed before the command loop (``tools.interp.source``).
* Contexts: sublime-syntax stack semantics (``docs/grammar-guide.md``). Only the context
  on top of the stack is searched; ``push`` / ``pop`` / ``set`` apply after the command
  completes. ``pop`` on the bottom ``main`` context is a no-op.
* ``reject: true``: the entry, once selected (first match in context order), fails the
  attempt at that line, mirroring ``CommandExecutionResult.error`` -> ``EXECUTION_ERROR``
  (``PSystemCommandFactory.java:180-187``): the command's regex matched, so no later
  command is tried. Inside the raw-mode preproc filter (no failure channel) a ``reject``
  entry just consumes its line.
* ``require_pop: true`` (with ``push``): a body that is still open when the block ends
  means the command never completed. Upstream skips such a command and tries the *next*
  command for the start line (``getCandidate``, ``PSystemCommandFactory.java:236-241``:
  ``isMultilineCommandOk`` returns ``null`` -> ``continue``); the start line fails only if
  none of those matches (``:169-175``). The interpreter therefore backtracks to the
  outermost still-open ``require_pop`` push (an outer multiline scan swallows the inner
  lines upstream, so the inner command never starts), restores the stack as it was
  before the push, and resumes at the *pushing line* with the rules after the pushing
  rule. When none matches the attempt fails at the pushing line. Frames closed by
  ``pop`` before the block ends are final, as are failures on lines inside a body.
* ``gives: <flag>`` / ``needs: <flag>``: order-free diagram flags over the entries that
  matched in the diagram's own command loop (never the raw-mode preproc filter). When the
  body ends and no ``require_pop`` frame is pending, an attempt where a matched entry
  ``needs`` a flag no matched entry ``gives`` fails at the block's ``@end`` line. Mirrors
  an exception thrown by ``checkFinalError`` / ``makeDiagramReady``-time code that
  ``PSystemBuilder`` catches as ``Throwable`` and reports as an execution error
  (``PSystemBuilder.java:275-280``). A backtrack to a ``require_pop`` push discards the
  entries matched after that push, flags included.
* ``trim: false`` (``single`` only): the entry matches ``Line.text`` (see
  ``tools.interp.rules``).
* ``kind: opaque``: after its ``parts`` match the line, the rest of the block (up to
  ``@end``) is swallowed as an unparsed body and accepted.

* Dispatch: ``tools.interp.dispatch`` (document-layer ``start_map``, top model per
  factory). A keyword no factory serves is ``PSystemUnsupported``
  (``PSystemErrorUtils.java:58-59``, ``PSystemBuilder.java:283-284``), which is not a
  ``PSystemError`` and so is accepted (``diagram``/``model`` ``None``), as the oracle
  reports it.
* Empty bodies: ``PSystemCommandFactory`` rejects them at the start line; non-command
  factories differ (``PSystemWelcomeFactory`` accepts *only* an empty ``@startuml``,
  ``JsonDiagramFactory`` accepts one). A model opts out of the rejection by declaring an
  ``empty`` context: the body lines followed by the ``@end`` line are run through it.
  ``empty_needs_end: true`` (model key) additionally refuses a block that has a start
  line but no end line: the source then has one line, and ``PSystemWelcomeFactory``
  needs exactly two (``eggs/PSystemWelcomeFactory.java:52``). Without the key a
  truncated empty block is accepted (``PSystemBasicFactory.createSystem`` returns the
  system when the iterator runs out, ``command/PSystemBasicFactory.java:101``).
* Raw mode (``raw=True``, the L1 hook): input is a raw block, not preprocessed text. If a
  ``layer: preproc`` model exists, every body line (after comment removal) is first
  offered to it, with its own context stack starting at ``main``; kinds, ``multiline``,
  ``join``, ``push``, ``pop`` and ``set`` behave exactly as for diagram rules. Lines a
  preproc rule matches are consumed; the rest go to the diagram. Upstream preprocesses
  the whole block before any factory runs (``BlockUmlBuilder.java:95``), so this runs as
  a filter once per block: every factory attempt sees the same lines, which is the same
  as resetting the preproc stack per attempt. A block whose non-blank lines are all
  consumed is an empty body. With ``raw=False`` (L2 input, already preprocessed) the
  preproc model is ignored.

Known semantic gaps (upstream behavior the model cannot represent, so the interpreter
may accept what the jar rejects): ``executeArg``/``execute`` results (e.g. unknown
colors, duplicate entities, ``CommandExecutionResult.error``), ``finalVerification``,
``isCommandForbidden``, ``checkFinalError`` / ``isIncomplete``
(``PSystemCommandFactory.java:157-170``), multi-pass diagrams (``getRequiredPass``),
``syntaxWithFinalBracket`` handling, abstract
``isLineConsistent`` of bracket commands, error *scores* beyond line progress, and
``Throwable`` crashes inside a factory (``:275-281``). Regex semantics are Java's
(``tools.model.java_regex``); see ``tools.interp.compile``.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import regex

from tools.interp import STATUS_ERROR, STATUS_OK, STATUS_REJECT, STATUS_TIMEOUT, Verdict
from tools.interp.compile import PartError
from tools.interp.dispatch import Dispatcher
from tools.interp.rules import ACTION_POP, ACTION_PUSH, ACTION_SET, Rule, RuleBook
from tools.interp.scan import BlockTimeout, Deadline
from tools.interp.source import Block, Line, split_block
from tools.model import ResolvedModel, ResolvedModels
from tools.model.java_regex import JavaRegexError

MAIN_CONTEXT = "main"
EMPTY_CONTEXT = "empty"
PREPROC_LAYER = "preproc"
DEFAULT_TIMEOUT_S = 10.0
MODEL_ERRORS = (regex.error, KeyError, PartError, JavaRegexError)
_Step = tuple[Rule, int, int]


def _verdict(
    status: str, model: ResolvedModel | None = None, failed: Line | None = None
) -> Verdict:
    failure = {"line": failed.number, "text": failed.text} if failed else None
    return {
        "accepted": status == STATUS_OK,
        "diagram": model.diagram if model else None,
        "first_failure": failure,  # type: ignore[typeddict-item]
        "model": model.id if model else None,
        "status": status,  # type: ignore[typeddict-item]
    }


def _is_empty(body: list[Line]) -> bool:
    return not any(line.trimmed for line in body)


def _truncated(model: ResolvedModel, block: Block) -> bool:
    """A ``empty_needs_end`` model refuses a block that has a start line but no end line."""
    return model.empty_needs_end and block.start is not None and block.end is None


def _preproc_model(models: ResolvedModels) -> ResolvedModel | None:
    return next((m for m in models.values() if m.layer == PREPROC_LAYER), None)


def _apply(stack: list[str], rule: Rule) -> None:
    if rule.action == ACTION_PUSH:
        stack.append(rule.target)
    elif rule.action == ACTION_SET:
        stack[-1] = rule.target
    elif rule.action == ACTION_POP and len(stack) > 1:
        stack.pop()


@dataclass(frozen=True)
class _Resume:
    """Backtracking point of a ``require_pop`` push: its line, prior stack, next rule."""

    index: int
    stack: tuple[str, ...]
    next_rule: int
    flagged: int  # flag-carrying rules matched before the push; later ones are discarded


def _track(
    frames: list[_Resume | None], stack: list[str], step: _Step, i: int, flagged: int
) -> None:
    """Mirror push/pop in ``frames`` (one slot per stack frame) before ``_apply``."""
    rule = step[0]
    if rule.action == ACTION_PUSH:
        resume = _Resume(i, tuple(stack), step[2] + 1, flagged)
        frames.append(resume if rule.require_pop else None)
    elif rule.action == ACTION_POP and len(frames) > 1:
        frames.pop()


def _closing_line(block: Block, lines: list[Line]) -> Line:
    """The block's ``@end`` line, else its last line (final-state failures)."""
    return block.end or (lines[-1] if lines else block.start or Line(1, "", ""))


def _unmet_need(flagged: list[Rule]) -> bool:
    """True when a matched entry ``needs`` a flag that no matched entry ``gives``."""
    given = {rule.gives for rule in flagged}
    return any(rule.needs and rule.needs not in given for rule in flagged)


class Interpreter:
    """Runs blocks against resolved models; compiled rules are reused across blocks."""

    def __init__(
        self,
        models: ResolvedModels,
        start_map: Mapping[str, Sequence[str]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._dispatch = Dispatcher(models, start_map)
        self._preproc = _preproc_model(models)
        self._clock = clock
        self._book = RuleBook()

    def accepts(
        self, block_text: str, timeout_s: float = DEFAULT_TIMEOUT_S, raw: bool = False
    ) -> Verdict:
        """Contract I3. Line numbers are 1-based within ``block_text``."""
        block = split_block(block_text)
        deadline = Deadline(timeout_s, self._clock)
        try:
            if raw and self._preproc is not None:
                body = self._preprocess(self._preproc, block.body, deadline)
                block = Block(block.start, block.keyword, body, block.end)
            return self._decide(block, deadline)
        except BlockTimeout:
            return _verdict(STATUS_TIMEOUT)
        except MODEL_ERRORS:
            return _verdict(STATUS_ERROR)

    def _decide(self, block: Block, deadline: Deadline) -> Verdict:
        anchor = block.start or Line(1, "", "")
        cands = self._dispatch.plan(block.keyword)
        if cands is None:
            return _verdict(STATUS_OK)
        best: tuple[int, Line] = (-1, anchor)
        for model in cands:
            failed = self._attempt(model, block, deadline)
            if failed is None:
                return _verdict(STATUS_OK, model)
            if failed[0] > best[0]:
                best = failed
        return _verdict(STATUS_REJECT, failed=best[1])

    def _attempt(
        self, model: ResolvedModel, block: Block, deadline: Deadline
    ) -> tuple[int, Line] | None:
        """``(progress, line)`` of the first rejected line, or ``None`` if accepted."""
        lines, context = block.body, MAIN_CONTEXT
        if _is_empty(block.body):
            if EMPTY_CONTEXT not in model.contexts or _truncated(model, block):
                return -1, block.start or Line(1, "", "")
            lines = block.body + ([block.end] if block.end else [])
            context = EMPTY_CONTEXT
        failed = self._run(model, lines, context, deadline)
        if failed is None:
            return None
        return failed, lines[failed] if failed < len(lines) else _closing_line(block, lines)

    def _run(
        self, model: ResolvedModel, body: list[Line], context: str, deadline: Deadline
    ) -> int | None:
        """Body index of the first line no command accepts, or ``None`` if all pass.

        ``len(body)`` means the final-state check failed (an unmet ``needs`` flag).
        """
        stack = [context]
        frames: list[_Resume | None] = [None]
        flagged: list[Rule] = []
        i, first = 0, 0
        while True:
            if i >= len(body):
                pending = next((f for f in frames if f is not None), None)
                if pending is None:
                    return len(body) if _unmet_need(flagged) else None
                stack, frames = list(pending.stack), [None]
                i, first = pending.index, pending.next_rule
                del flagged[pending.flagged :]
            step = self._candidate(model, stack[-1], body, i, deadline, first)
            first = 0
            if step is None:
                if body[i].trimmed:
                    return i
                i += 1
            elif step[0].reject:
                return i
            else:
                _track(frames, stack, step, i, len(flagged))
                flagged.extend([step[0]] if step[0].gives or step[0].needs else [])
                _apply(stack, step[0])
                i = step[1]

    def _preprocess(self, model: ResolvedModel, body: list[Line], deadline: Deadline) -> list[Line]:
        """Lines the preproc model does not consume, in order (raw mode)."""
        stack = [MAIN_CONTEXT]
        kept: list[Line] = []
        i = 0
        while i < len(body):
            step = self._candidate(model, stack[-1], body, i, deadline)
            if step is None:
                kept.append(body[i])
                i += 1
            else:
                _apply(stack, step[0])
                i = step[1]
        return kept

    def _candidate(
        self,
        model: ResolvedModel,
        context: str,
        body: list[Line],
        i: int,
        deadline: Deadline,
        first: int = 0,
    ) -> _Step | None:
        """``PSystemCommandFactory.getCandidate`` (:223-247), from rule ``first`` on.

        Returns ``(rule, next line index, rule index)``.
        """
        rules = self._book.rules(model, context)
        for index in range(first, len(rules)):
            nxt = rules[index].advance(body, i, deadline)
            if nxt is not None:
                return rules[index], nxt, index
        return None


_LAST: list[tuple[ResolvedModels, Mapping[str, Sequence[str]] | None, Interpreter]] = []


def _interpreter_for(
    models: ResolvedModels, start_map: Mapping[str, Sequence[str]] | None
) -> Interpreter:
    """Single-slot cache keyed by object identity, so compiled rules persist across calls.

    ``models`` must not be mutated between calls; pass a new mapping instead.
    """
    if _LAST and _LAST[0][0] is models and _LAST[0][1] is start_map:
        return _LAST[0][2]
    interpreter = Interpreter(models, start_map)
    _LAST[:] = [(models, start_map, interpreter)]
    return interpreter


def accepts(
    models: ResolvedModels,
    block_text: str,
    *,
    raw: bool = False,
    start_map: Mapping[str, Sequence[str]] | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> Verdict:
    """Would upstream accept ``block_text`` (``@startX`` ... ``@endX`` included)?

    ``start_map`` maps a start keyword (``"uml"`` or ``"@startuml"``) to the ordered
    factories or model ids to try; without it the document-layer model's ``start_map``
    is used, else the keyword is resolved like ``DiagramType.findStartTypes`` (see
    ``tools.interp.dispatch``). A block with no ``@start`` line is treated as a bare
    body tried against every diagram model. ``raw=True`` runs the preproc-layer model
    first (see the module docstring).
    """
    return _interpreter_for(models, start_map).accepts(block_text, timeout_s, raw)
