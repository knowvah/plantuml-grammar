// Loads and validates the engine JSON (contract C1, plans/ts-engine/contracts.md#c1).
// Mirrors the lazy compile-once memoization in tools/interp/rules.py:92-104 and
// tools/interp/compile.py:56-67.
import { ENGINE_FORMAT } from "./types.js";
import type { EngineJson, EngineModelJson, EntryJson } from "./types.js";

/** The only regex flag set the engine JSON may carry. */
const PATTERN_FLAGS = "u";

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

  /** The compiled regex for `id`, compiled on first use. */
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

  #compilePattern(id: number): RegExp {
    const p = this.#json.patterns[id];
    if (p === undefined) {
      throw new RangeError(`pattern ${id} out of range (0..${this.patternCount - 1})`);
    }
    if ("unsupported" in p) {
      throw new ModelError(p.unsupported);
    }
    try {
      return this.#compile(p.source, PATTERN_FLAGS);
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
  patterns.forEach((p, i) => validatePattern(p, `/patterns/${i}`));
  const table = requireArray(root["context_table"], "/context_table");
  table.forEach((list, i) => validateEntryList(list, `/context_table/${i}`, patterns.length));
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

function validatePattern(p: unknown, pointer: string): void {
  const rec = requireRecord(p, pointer);
  if ("unsupported" in rec) {
    if (typeof rec["unsupported"] !== "string") {
      fail(`${pointer}/unsupported`, "expected a string");
    }
    return;
  }
  if (typeof rec["source"] !== "string" || typeof rec["flags"] !== "string") {
    fail(pointer, "expected {source, flags} or {unsupported}");
  }
  if (rec["flags"] !== PATTERN_FLAGS) {
    fail(`${pointer}/flags`, `expected "${PATTERN_FLAGS}"`);
  }
}

function validateEntryList(list: unknown, pointer: string, patternCount: number): void {
  requireArray(list, pointer).forEach((e, i) => validateEntry(e, `${pointer}/${i}`, patternCount));
}

function validateEntry(entry: unknown, pointer: string, patternCount: number): void {
  const rec = requireRecord(entry, pointer);
  requireIndex(rec["start"], `${pointer}/start`, patternCount);
  if (rec["end"] !== undefined) {
    requireIndex(rec["end"], `${pointer}/end`, patternCount);
  }
  if (rec["join"] !== undefined) {
    const join = requireRecord(rec["join"], `${pointer}/join`);
    requireIndex(join["prefix"], `${pointer}/join/prefix`, patternCount);
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
