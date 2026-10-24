// Port of tools/interp/engine.py: the interpreter that runs a block through the model the
// way upstream runs commands. The semantics it mirrors (all at 97a5992) are documented in
// the module docstring of the Python file and summarised here:
//
// * Factory loop (`PSystemBuilder.java:257-287`): the candidates for the start keyword are
//   tried in order; the first that accepts wins. If all fail, the failure that got
//   furthest is reported (`PSystemError.score`, strict `>`, so the first candidate wins
//   ties). A keyword no factory serves is `PSystemUnsupported`: accepted, null diagram.
// * Command loop (`PSystemCommandFactory.java:107-150, 223-247`): commands in context order
//   for the current line; a blank line is skipped only when no command matched it.
// * `reject`: the selected entry fails the attempt at its line.
// * `require_pop`: a push still open at the end of the body backtracks to the outermost
//   open frame, restores the stack, discards flags collected after the push, and resumes at
//   the pushing line with the next rule.
// * `gives` / `needs`: order-free flags over the entries matched in the diagram's loop;
//   an unmet need fails at the block's end line.
// * `opaque`: the rest of the block is swallowed.
// * Empty bodies: rejected at the start line unless the model has an `empty` context, which
//   then sees the body followed by the end line; `empty_needs_end` refuses a truncated block.
// * Raw mode: the preproc-layer model filters the body once per block, before any attempt.
//
// Model problems (unsupported or uncompilable pattern, missing context) give status
// `error`; an exhausted time budget gives `timeout`. The time budget is cooperative (D5).
import { BlockTimeout, Deadline } from "./deadline.js";
import type { Clock } from "./deadline.js";
import { Dispatcher } from "./dispatch.js";
import type { ModelRef, StartMap } from "./dispatch.js";
import { ModelError, UnknownContextError } from "./load.js";
import type { EngineModel } from "./load.js";
import { ACTION_POP, ACTION_PUSH, ACTION_SET, RuleBook } from "./rules.js";
import type { Rule } from "./rules.js";
import { splitBlock } from "./source.js";
import type { Block, Line } from "./source.js";
import {
  STATUS_ERROR,
  STATUS_OK,
  STATUS_REJECT,
  STATUS_TIMEOUT,
} from "./types.js";
import type { Status, Verdict } from "./types.js";

export const MAIN_CONTEXT = "main";
export const EMPTY_CONTEXT = "empty";
export const PREPROC_LAYER = "preproc";
export const DEFAULT_TIMEOUT_MS = 10_000;
/** Progress value of a failure before any line was consumed (an empty-body rejection). */
const NO_PROGRESS = -1;

export interface InterpreterOptions {
  /** Start keyword (`"uml"` or `"@startuml"`) to the ordered factories or model ids to try. */
  startMap?: Record<string, string[]>;
  /** Monotonic clock in milliseconds; defaults to `performance.now`. */
  clock?: Clock;
}

export interface AcceptsOptions {
  /** Input is a raw block: run the preproc-layer model first. */
  raw?: boolean;
  timeoutMs?: number;
}

/** A matched rule, the index after it, and its position in the context's rule list. */
interface Step {
  readonly rule: Rule;
  readonly next: number;
  readonly index: number;
}

/** Backtracking point of a `require_pop` push: its line, prior stack, next rule. */
interface Resume {
  readonly index: number;
  readonly stack: readonly string[];
  readonly nextRule: number;
  /** Flag-carrying rules matched before the push; later ones are discarded. */
  readonly flagged: number;
}

/** Mutable state of one `#run`: context stack, one frame slot per stack frame, flags. */
interface RunState {
  stack: string[];
  frames: (Resume | null)[];
  readonly flagged: Rule[];
}

/** Where the command loop is: the line index and the first rule to try there. */
interface Position {
  readonly i: number;
  readonly first: number;
}

/** Result of one loop iteration: stop with a verdict index, or continue at a position. */
type Outcome =
  | { readonly kind: "done"; readonly failed: number | null }
  | { readonly kind: "go"; readonly at: Position };

/** A rejected attempt: lines consumed when it failed and the line it failed at. */
interface Failure {
  readonly progress: number;
  readonly line: Line;
}

const EMPTY_LINE: Line = { number: 1, text: "", trimmed: "" };

function verdict(status: Status, model: ModelRef | null = null, failed: Line | null = null): Verdict {
  return {
    accepted: status === STATUS_OK,
    diagram: model?.model.diagram ?? null,
    model: model?.id ?? null,
    status,
    firstFailure: failed === null ? null : { line: failed.number, text: failed.text },
  };
}

const isEmpty = (body: readonly Line[]): boolean => !body.some((line) => line.trimmed !== "");

/** An `empty_needs_end` model refuses a block that has a start line but no end line. */
const truncated = (model: ModelRef, block: Block): boolean =>
  model.model.empty_needs_end && block.start !== null && block.end === null;

function apply(stack: string[], rule: Rule): void {
  if (rule.action === ACTION_PUSH) {
    stack.push(rule.target);
  } else if (rule.action === ACTION_SET) {
    stack[stack.length - 1] = rule.target;
  } else if (rule.action === ACTION_POP && stack.length > 1) {
    stack.pop();
  }
}

/** Mirror push/pop in `frames` (one slot per stack frame) before `apply`. */
function track(st: RunState, step: Step, i: number): void {
  if (step.rule.action === ACTION_PUSH) {
    const resume: Resume = {
      index: i,
      stack: [...st.stack],
      nextRule: step.index + 1,
      flagged: st.flagged.length,
    };
    st.frames.push(step.rule.requirePop ? resume : null);
  } else if (step.rule.action === ACTION_POP && st.frames.length > 1) {
    st.frames.pop();
  }
}

/** The block's end line, else its last line (final-state failures). */
const closingLine = (block: Block, lines: readonly Line[]): Line =>
  block.end ?? lines.at(-1) ?? block.start ?? EMPTY_LINE;

/** True when a matched entry `needs` a flag that no matched entry `gives`. */
function unmetNeed(flagged: readonly Rule[]): boolean {
  const given = new Set(flagged.map((rule) => rule.gives));
  return flagged.some((rule) => rule.needs !== "" && !given.has(rule.needs));
}

const isModelError = (error: unknown): boolean =>
  error instanceof ModelError ||
  error instanceof UnknownContextError ||
  // V8 running out of stack inside a regex.
  error instanceof RangeError;

/** Runs blocks against a loaded engine; compiled rules are reused across blocks. */
export class Interpreter {
  readonly #dispatch: Dispatcher;
  readonly #preproc: ModelRef | null;
  readonly #clock: Clock | undefined;
  readonly #book: RuleBook;

  constructor(engine: EngineModel, opts: InterpreterOptions = {}) {
    const models = Object.fromEntries(engine.models);
    const order = [...engine.models.keys()];
    this.#dispatch = new Dispatcher(models, order, engine.tops, opts.startMap);
    this.#preproc = findPreproc(engine);
    this.#clock = opts.clock;
    this.#book = new RuleBook(engine);
  }

  /** Contract C7. Line numbers are 1-based within `text`. */
  accepts(text: string, opts: AcceptsOptions = {}): Verdict {
    let block = splitBlock(text);
    const deadline = new Deadline(opts.timeoutMs ?? DEFAULT_TIMEOUT_MS, this.#clock);
    try {
      if ((opts.raw ?? false) && this.#preproc !== null) {
        const body = this.#preprocess(this.#preproc, block.body, deadline);
        block = { start: block.start, keyword: block.keyword, body, end: block.end };
      }
      return this.#decide(block, deadline);
    } catch (error) {
      if (error instanceof BlockTimeout) return verdict(STATUS_TIMEOUT);
      if (isModelError(error)) return verdict(STATUS_ERROR);
      throw error;
    }
  }

  #decide(block: Block, deadline: Deadline): Verdict {
    const candidates = this.#dispatch.plan(block.keyword);
    if (candidates === null) return verdict(STATUS_OK);
    let best: Failure = { progress: NO_PROGRESS, line: block.start ?? EMPTY_LINE };
    for (const model of candidates) {
      const failed = this.#attempt(model, block, deadline);
      if (failed === null) return verdict(STATUS_OK, model);
      if (failed.progress > best.progress) best = failed;
    }
    return verdict(STATUS_REJECT, null, best.line);
  }

  /** The first rejected line, or `null` if the model accepts the block. */
  #attempt(model: ModelRef, block: Block, deadline: Deadline): Failure | null {
    let lines = block.body;
    let context = MAIN_CONTEXT;
    if (isEmpty(block.body)) {
      if (!(EMPTY_CONTEXT in model.model.contexts) || truncated(model, block)) {
        return { progress: NO_PROGRESS, line: block.start ?? EMPTY_LINE };
      }
      lines = block.end === null ? block.body : [...block.body, block.end];
      context = EMPTY_CONTEXT;
    }
    const failed = this.#run(model.id, lines, context, deadline);
    if (failed === null) return null;
    return { progress: failed, line: lines[failed] ?? closingLine(block, lines) };
  }

  /**
   * Body index of the first line no command accepts, or `null` if all pass.
   * `body.length` means the final-state check failed (an unmet `needs` flag).
   */
  #run(modelId: string, body: readonly Line[], context: string, deadline: Deadline): number | null {
    const st: RunState = { stack: [context], frames: [null], flagged: [] };
    let out: Outcome = { kind: "go", at: { i: 0, first: 0 } };
    while (out.kind === "go") out = this.#tick(st, modelId, body, out.at, deadline);
    return out.failed;
  }

  /** One iteration of the command loop at `at`. */
  #tick(st: RunState, modelId: string, body: readonly Line[], at: Position, deadline: Deadline): Outcome {
    if (at.i >= body.length) return endOfBody(st, body.length);
    const step = this.#candidate(modelId, st.stack.at(-1) ?? MAIN_CONTEXT, body, at, deadline);
    if (step === null) {
      return body[at.i]?.trimmed === "" ? goTo(at.i + 1) : { kind: "done", failed: at.i };
    }
    if (step.rule.reject) return { kind: "done", failed: at.i };
    return goTo(commit(st, step, at.i));
  }

  /** Lines the preproc model does not consume, in order (raw mode). */
  #preprocess(model: ModelRef, body: readonly Line[], deadline: Deadline): Line[] {
    const stack = [MAIN_CONTEXT];
    const kept: Line[] = [];
    let i = 0;
    while (i < body.length) {
      const step = this.#candidate(model.id, stack.at(-1) ?? MAIN_CONTEXT, body, { i, first: 0 }, deadline);
      if (step === null) {
        kept.push(body[i] ?? EMPTY_LINE);
        i += 1;
      } else {
        apply(stack, step.rule);
        i = step.next;
      }
    }
    return kept;
  }

  /** `PSystemCommandFactory.getCandidate` (:223-247), from rule `at.first` on. */
  #candidate(
    modelId: string,
    context: string,
    body: readonly Line[],
    at: Position,
    deadline: Deadline,
  ): Step | null {
    const rules = this.#book.rules(modelId, context);
    for (let index = at.first; index < rules.length; index += 1) {
      const rule = rules[index];
      if (rule === undefined) break;
      const next = rule.advance(body, at.i, deadline);
      if (next !== null) return { rule, next, index };
    }
    return null;
  }
}

/** The end of the body: final-state check, or back to the outermost open `require_pop` push. */
function endOfBody(st: RunState, length: number): Outcome {
  const pending = st.frames.find((f): f is Resume => f !== null);
  if (pending === undefined) return { kind: "done", failed: unmetNeed(st.flagged) ? length : null };
  restore(st, pending);
  return { kind: "go", at: { i: pending.index, first: pending.nextRule } };
}

const goTo = (i: number): Outcome => ({ kind: "go", at: { i, first: 0 } });

/** Back to a `require_pop` push: its stack, no open frames, flags from before it. */
function restore(st: RunState, pending: Resume): void {
  st.stack = [...pending.stack];
  st.frames = [null];
  st.flagged.splice(pending.flagged);
}

/** Record `step` (frame, flags, stack) and return the index after it. */
function commit(st: RunState, step: Step, i: number): number {
  track(st, step, i);
  if (step.rule.gives !== "" || step.rule.needs !== "") st.flagged.push(step.rule);
  apply(st.stack, step.rule);
  return step.next;
}

function findPreproc(engine: EngineModel): ModelRef | null {
  for (const [id, model] of engine.models) {
    if (model.layer === PREPROC_LAYER) return { id, model };
  }
  return null;
}

export interface CachedAcceptsOptions extends AcceptsOptions {
  startMap?: Record<string, string[]>;
}

interface Slot {
  readonly engine: EngineModel;
  readonly startMap: StartMap | undefined;
  readonly interpreter: Interpreter;
}

let lastSlot: Slot | null = null;

/**
 * Would upstream accept `text`? Single-slot cache keyed by engine (and `startMap`)
 * identity, so compiled rules persist across calls. The engine must not be mutated.
 */
export function accepts(engine: EngineModel, text: string, opts: CachedAcceptsOptions = {}): Verdict {
  const { startMap, ...rest } = opts;
  if (lastSlot === null || lastSlot.engine !== engine || lastSlot.startMap !== startMap) {
    const interpreter = new Interpreter(engine, startMap === undefined ? {} : { startMap });
    lastSlot = { engine, startMap, interpreter };
  }
  return lastSlot.interpreter.accepts(text, rest);
}
