// Contract types for the engine JSON (plans/ts-engine/contracts.md#c1) and the
// public verdict API (#c7). Mirrors the JSON emitted by the Python model builder.

/** The only `engine_format` value this loader accepts. */
export const ENGINE_FORMAT = 1;

export const STATUS_OK = "ok";
export const STATUS_REJECT = "reject";
export const STATUS_TIMEOUT = "timeout";
export const STATUS_ERROR = "error";

export type Status =
  | typeof STATUS_OK
  | typeof STATUS_REJECT
  | typeof STATUS_TIMEOUT
  | typeof STATUS_ERROR;

export interface FirstFailure {
  line: number;
  text: string;
}

export interface Verdict {
  accepted: boolean;
  diagram: string | null;
  model: string | null;
  status: Status;
  firstFailure: FirstFailure | null;
}

/** A C1a `split`: sticky head, native JSON leaf, sticky tail, bounded-depth fast regex. */
export interface SplitJson {
  head: number;
  native: string;
  tail: number;
  fast: number | null;
  fast_final: "accept" | "reject";
}

/**
 * A compiled-regex pattern (`flags` "u", or "uy" for a split head/tail), a marker for one
 * the JS translator cannot express, a C1a `split`, or an `any` union of pattern ids.
 * A whole-line, split or any pattern may carry a `guard`: a regex source (flags "u") that
 * every line the pattern matches also matches.
 */
export type PatternJson =
  | { source: string; flags: string; guard?: string }
  | { unsupported: string }
  | { split: SplitJson; guard?: string }
  | { any: number[]; guard?: string };

export interface EntryJson {
  command: string;
  kind: "single" | "multiline" | "multiline-bracket" | "opaque";
  /** Pattern id for the whole-line start regex. */
  start: number;
  /** Optional multiline end pattern id. */
  end?: number;
  join?: { max_lines: number; prefix: number };
  action: "" | "push" | "pop" | "set";
  target: string;
  require_pop: boolean;
  reject: boolean;
  gives: string;
  needs: string;
  untrimmed: boolean;
}

export interface EngineModelJson {
  layer: "document" | "preproc" | "diagram" | "shared";
  diagram: string | null;
  factory: string | null;
  glue_units: boolean;
  empty_needs_end: boolean;
  start_map: Record<string, string[]>;
  includes: string[];
  /** Context name -> index into `context_table`. */
  contexts: Record<string, number>;
}

export interface EngineJson {
  engine_format: number;
  pin: string;
  patterns: PatternJson[];
  context_table: EntryJson[][];
  models: Record<string, EngineModelJson>;
  /** Every key of `models` once, in ResolvedModels insertion order. */
  model_order: string[];
  /** Factory name -> model id. */
  tops: Record<string, string>;
}
