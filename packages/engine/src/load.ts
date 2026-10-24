// Loads and validates the engine JSON (contract C1, plans/ts-engine/contracts.md#c1).
// Mirrors the lazy compile-once memoization in tools/interp/rules.py:92-104 and
// tools/interp/compile.py:56-67.
import { AnyMatcher, FAST_ACCEPT, FAST_REJECT, NATIVE_KINDS, RegexMatcher, SplitMatcher } from "./matcher.js";
import type { Matcher, SplitParts } from "./matcher.js";
import { ENGINE_FORMAT } from "./types.js";
import type { EngineJson, EngineModelJson, EntryJson, PatternJson, SplitJson } from "./types.js";

/** Whole-line regex flags. */
const PATTERN_FLAGS = "u";
/** Sticky flags of a split head/tail sub-pattern. */
const STICKY_FLAGS = "uy";

/** The engine JSON is structurally invalid; `pointer` is an RFC 6901 JSON pointer. */
export class EngineFormatError extends Error {
  readonly pointer: string;

  constructor(pointer: string, detail: string) {
    super(`${pointer}: ${detail}`);
    this.name = "EngineFormatError";
    this.pointer = pointer;
  }
}

/** A pattern is unusable: unsupported by the translator, or failed to compile. */
export class ModelError extends Error {
  constructor(message: string, options?: { cause: unknown }) {
    super(message, options);
    this.name = "ModelError";
  }
}

/** A model has no context with the requested name. */
export class UnknownContextError extends Error {
  constructor(modelId: string, name: string) {
    super(`model ${modelId} has no context ${name}`);
    this.name = "UnknownContextError";
  }
}

export type CompileHook = (source: string, flags: string) => RegExp;

export interface LoadOptions {
  /** Regex compile hook; defaults to `new RegExp`. Lets tests count compilations. */
  compile?: CompileHook;
}

const defaultCompile: CompileHook = (source, flags) => new RegExp(source, flags);

/** Validated engine model with lazily compiled, cached patterns. */
export class EngineModel {
  /** Models keyed by id, iterated in `model_order`. */
  readonly models: ReadonlyMap<string, EngineModelJson>;
  readonly tops: Readonly<Record<string, string>>;
  readonly #json: EngineJson;
  readonly #compile: CompileHook;
  readonly #cache = new Map<number, RegExp>();
  readonly #matchers = new Map<number, Matcher>();

  constructor(json: EngineJson, compile: CompileHook) {
    this.#json = json;
    this.#compile = compile;
    this.models = new Map(json.model_order.map((id) => [id, requireModel(json, id)]));
    this.tops = json.tops;
  }

  get patternCount(): number {
    return this.#json.patterns.length;
  }

  get compiledCount(): number {
    return this.#cache.size;
  }

  /** The matcher for `id` (regex, split or any), built on first use. */
  matcher(id: number): Matcher {
    const cached = this.#matchers.get(id);
    if (cached !== undefined) {
      return cached;
    }
    const built = this.#buildMatcher(id);
    this.#matchers.set(id, built);
    return built;
  }

  /** The compiled regex for plain pattern `id`, compiled on first use. */
  pattern(id: number): RegExp {
    const cached = this.#cache.get(id);
    if (cached !== undefined) {
      return cached;
    }
    const re = this.#compilePattern(id);
    this.#cache.set(id, re);
    return re;
  }

  /** Entries of context `name` in model `modelId`. */
  context(modelId: string, name: string): EntryJson[] {
    const index = this.models.get(modelId)?.contexts[name];
    const entries = index === undefined ? undefined : this.#json.context_table[index];
    if (entries === undefined) {
      throw new UnknownContextError(modelId, name);
    }
    return entries;
  }

  #patternAt(id: number): PatternJson {
    const p = this.#json.patterns[id];
    if (p === undefined) {
      throw new RangeError(`pattern ${id} out of range (0..${this.patternCount - 1})`);
    }
    return p;
  }

  #buildMatcher(id: number): Matcher {
    const p = this.#patternAt(id);
    if ("split" in p) {
      return new SplitMatcher(this.#splitParts(p.split));
    }
    if ("any" in p) {
      return new AnyMatcher(p.any.map((member) => this.matcher(member)));
    }
    return new RegexMatcher(this.pattern(id));
  }

  #splitParts(split: SplitJson): SplitParts {
    const ends = NATIVE_KINDS[split.native];
    if (ends === undefined) {
      throw new ModelError(`unknown native kind ${split.native}`);
    }
    return {
      head: this.pattern(split.head),
      ends,
      tail: this.pattern(split.tail),
      fast: split.fast === null ? null : this.matcher(split.fast),
      fastFinal: split.fast_final,
    };
  }

  #compilePattern(id: number): RegExp {
    const p = this.#patternAt(id);
    if ("unsupported" in p) {
      throw new ModelError(p.unsupported);
    }
    if (!("source" in p)) {
      throw new ModelError(`pattern ${id} is not a plain regex`);
    }
    try {
      return this.#compile(p.source, p.flags);
    } catch (cause) {
      throw new ModelError(`pattern ${id} failed to compile`, { cause });
    }
  }
}

function requireModel(json: EngineJson, id: string): EngineModelJson {
  const model = json.models[id];
  if (model === undefined) {
    throw new EngineFormatError("/model_order", `unknown model ${id}`);
  }
  return model;
}

/** Validates `json` and wraps it; throws `EngineFormatError` with a JSON pointer. */
export function loadEngine(json: unknown, options: LoadOptions = {}): EngineModel {
  const root = requireRecord(json, "");
  if (root["engine_format"] !== ENGINE_FORMAT) {
    fail("/engine_format", `expected ${ENGINE_FORMAT}, got ${String(root["engine_format"])}`);
  }
  const patterns = requireArray(root["patterns"], "/patterns");
  patterns.forEach((p, i) => validatePattern(p, `/patterns/${i}`, patterns.length));
  const sticky = validateReferences(patterns);
  const table = requireArray(root["context_table"], "/context_table");
  table.forEach((list, i) =>
    validateEntryList(list, `/context_table/${i}`, patterns.length, sticky),
  );
  const models = requireRecord(root["models"], "/models");
  for (const [id, model] of Object.entries(models)) {
    validateModel(model, `/models/${escapeToken(id)}`, table.length);
  }
  validateModelOrder(root["model_order"], models);
  validateTops(root["tops"], models);
  return new EngineModel(json as EngineJson, options.compile ?? defaultCompile);
}

function fail(pointer: string, detail: string): never {
  throw new EngineFormatError(pointer, detail);
}

function escapeToken(token: string): string {
  return token.replaceAll("~", "~0").replaceAll("/", "~1");
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function requireRecord(v: unknown, pointer: string): Record<string, unknown> {
  return isRecord(v) ? v : fail(pointer, "expected an object");
}

function requireArray(v: unknown, pointer: string): unknown[] {
  return Array.isArray(v) ? v : fail(pointer, "expected an array");
}

function requireIndex(v: unknown, pointer: string, length: number): void {
  if (typeof v !== "number" || !Number.isInteger(v) || v < 0 || v >= length) {
    fail(pointer, `expected an integer index in 0..${length - 1}`);
  }
}

function validatePattern(p: unknown, pointer: string, count: number): void {
  const rec = requireRecord(p, pointer);
  if ("unsupported" in rec) {
    if (typeof rec["unsupported"] !== "string") {
      fail(`${pointer}/unsupported`, "expected a string");
    }
  } else if ("split" in rec) {
    validateSplit(rec["split"], `${pointer}/split`, count);
  } else if ("any" in rec) {
    requireArray(rec["any"], `${pointer}/any`).forEach((id, i) =>
      requireIndex(id, `${pointer}/any/${i}`, count),
    );
  } else {
    validateSource(rec, pointer);
  }
}

function validateSource(rec: Record<string, unknown>, pointer: string): void {
  if (typeof rec["source"] !== "string" || typeof rec["flags"] !== "string") {
    fail(pointer, "expected {source, flags}, {unsupported}, {split} or {any}");
  }
  if (rec["flags"] !== PATTERN_FLAGS && rec["flags"] !== STICKY_FLAGS) {
    fail(`${pointer}/flags`, `expected "${PATTERN_FLAGS}" or "${STICKY_FLAGS}"`);
  }
}

function validateSplit(split: unknown, pointer: string, count: number): void {
  const rec = requireRecord(split, pointer);
  requireIndex(rec["head"], `${pointer}/head`, count);
  requireIndex(rec["tail"], `${pointer}/tail`, count);
  if (rec["fast"] !== null) {
    requireIndex(rec["fast"], `${pointer}/fast`, count);
  }
  if (rec["fast_final"] !== FAST_ACCEPT && rec["fast_final"] !== FAST_REJECT) {
    fail(`${pointer}/fast_final`, `expected "${FAST_ACCEPT}" or "${FAST_REJECT}"`);
  }
  if (typeof rec["native"] !== "string" || !Object.hasOwn(NATIVE_KINDS, rec["native"])) {
    fail(`${pointer}/native`, `unknown native kind ${String(rec["native"])}`);
  }
}

function isStickySource(p: unknown): boolean {
  return isRecord(p) && p["flags"] === STICKY_FLAGS;
}

/** Checks which patterns may reference which; returns the ids of the sticky ones. */
function validateReferences(patterns: unknown[]): ReadonlySet<number> {
  const sticky = new Set<number>();
  patterns.forEach((p, i) => isStickySource(p) && sticky.add(i));
  const used = new Set<number>();
  patterns.forEach((p, i) => {
    const rec = p as Record<string, unknown>; // validated as records by validatePattern
    if (isRecord(rec["split"])) {
      validateSplitUse(rec["split"], `/patterns/${i}/split`, sticky, used);
    } else if (Array.isArray(rec["any"])) {
      rec["any"].forEach((id: number, k: number) => {
        if (sticky.has(id) || Array.isArray((patterns[id] as Record<string, unknown>)["any"])) {
          fail(`/patterns/${i}/any/${k}`, "expected a whole-line or split pattern");
        }
      });
    }
  });
  for (const id of sticky) {
    if (!used.has(id)) {
      fail(`/patterns/${id}/flags`, `"${STICKY_FLAGS}" only as a split head or tail`);
    }
  }
  return sticky;
}

function validateSplitUse(
  split: Record<string, unknown>,
  pointer: string,
  sticky: ReadonlySet<number>,
  used: Set<number>,
): void {
  for (const part of ["head", "tail"]) {
    const id = split[part] as number;
    if (!sticky.has(id)) {
      fail(`${pointer}/${part}`, `expected a "${STICKY_FLAGS}" source pattern`);
    }
    used.add(id);
  }
  if (typeof split["fast"] === "number" && sticky.has(split["fast"])) {
    fail(`${pointer}/fast`, "expected a whole-line pattern");
  }
}

function validateEntryList(
  list: unknown,
  pointer: string,
  patternCount: number,
  sticky: ReadonlySet<number>,
): void {
  requireArray(list, pointer).forEach((e, i) =>
    validateEntry(e, `${pointer}/${i}`, patternCount, sticky),
  );
}

/** Entry pattern references are whole-line: in range and never a sticky sub-pattern. */
function requireEntryPattern(
  v: unknown,
  pointer: string,
  count: number,
  sticky: ReadonlySet<number>,
): void {
  requireIndex(v, pointer, count);
  if (sticky.has(v as number)) {
    fail(pointer, `pattern is a "${STICKY_FLAGS}" sub-pattern`);
  }
}

function validateEntry(
  entry: unknown,
  pointer: string,
  count: number,
  sticky: ReadonlySet<number>,
): void {
  const rec = requireRecord(entry, pointer);
  requireEntryPattern(rec["start"], `${pointer}/start`, count, sticky);
  if (rec["end"] !== undefined) {
    requireEntryPattern(rec["end"], `${pointer}/end`, count, sticky);
  }
  if (rec["join"] !== undefined) {
    const join = requireRecord(rec["join"], `${pointer}/join`);
    requireEntryPattern(join["prefix"], `${pointer}/join/prefix`, count, sticky);
  }
}

function validateModel(model: unknown, pointer: string, tableLength: number): void {
  const rec = requireRecord(model, pointer);
  const contexts = requireRecord(rec["contexts"], `${pointer}/contexts`);
  for (const [name, index] of Object.entries(contexts)) {
    requireIndex(index, `${pointer}/contexts/${escapeToken(name)}`, tableLength);
  }
}

function validateModelOrder(order: unknown, models: Record<string, unknown>): void {
  const ids = requireArray(order, "/model_order");
  const seen = new Set<unknown>();
  ids.forEach((id, i) => {
    if (typeof id !== "string" || !(id in models) || seen.has(id)) {
      fail(`/model_order/${i}`, "expected each model id exactly once");
    }
    seen.add(id);
  });
  if (seen.size !== Object.keys(models).length) {
    fail("/model_order", "must list every model id exactly once");
  }
}

function validateTops(tops: unknown, models: Record<string, unknown>): void {
  for (const [factory, id] of Object.entries(requireRecord(tops, "/tops"))) {
    if (typeof id !== "string" || !(id in models)) {
      fail(`/tops/${escapeToken(factory)}`, "expected an existing model id");
    }
  }
}
