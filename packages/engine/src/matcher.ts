// Matchers for engine patterns (contract C8, plans/ts-engine/contracts.md#c8): a plain
// regex, a C1a `split` (sticky head, native JSON leaf, sticky tail) and an `any` union.
// The Python reference is the original recursive regex (tools/interp/compile.py); the
// split reproduces `HEAD leaf TAIL` matched against the whole line.
import type { Deadline } from "./deadline.js";
import { jsonBlockBodyEnds, jsonDataInvalidEnds } from "./native.js";

/** Tests a whole line against one engine pattern. */
export interface Matcher {
  test(text: string, deadline: Deadline): boolean;
}

/** `ends(s, i)`: every `j` where the native leaf matched at `i` can end. */
export type NativeEnds = (s: string, i: number) => number[];

export const NATIVE_JSON_BLOCK_BODY = "json-block-body";
export const NATIVE_JSON_DATA_INVALID = "json-data-invalid";
export const FAST_ACCEPT = "accept";
export const FAST_REJECT = "reject";

/** The native leaf kinds, keyed as in the engine JSON `split.native`. */
export const NATIVE_KINDS: Readonly<Record<string, NativeEnds>> = {
  [NATIVE_JSON_BLOCK_BODY]: jsonBlockBodyEnds,
  [NATIVE_JSON_DATA_INVALID]: jsonDataInvalidEnds,
};

export type FastFinal = typeof FAST_ACCEPT | typeof FAST_REJECT;

/** A whole-line regex. */
export class RegexMatcher implements Matcher {
  readonly #re: RegExp;

  constructor(re: RegExp) {
    this.#re = re;
  }

  test(text: string, deadline: Deadline): boolean {
    return deadline.test(this.#re, text);
  }
}

/** Union of alternatives: true when any matches. */
export class AnyMatcher implements Matcher {
  readonly #members: readonly Matcher[];

  constructor(members: readonly Matcher[]) {
    this.#members = members;
  }

  test(text: string, deadline: Deadline): boolean {
    return this.#members.some((m) => m.test(text, deadline));
  }
}

/**
 * A pattern behind a guard: a small regex that every match of the pattern also matches
 * (tools/emit/guard.py). A line the guard rejects is rejected without building, compiling
 * or running the pattern; `build` runs on the first line the guard passes.
 */
export class GuardedMatcher implements Matcher {
  readonly #guard: RegExp;
  readonly #build: () => Matcher;
  #inner: Matcher | null = null;

  constructor(guard: RegExp, build: () => Matcher) {
    this.#guard = guard;
    this.#build = build;
  }

  test(text: string, deadline: Deadline): boolean {
    if (!deadline.test(this.#guard, text)) {
      return false;
    }
    this.#inner ??= this.#build();
    return this.#inner.test(text, deadline);
  }
}

export interface SplitParts {
  /** Sticky `(?<=^(?:HEAD))`, tested at `lastIndex = i`. */
  readonly head: RegExp;
  readonly ends: NativeEnds;
  /** Sticky `(?:TAIL)(?:LT)?$`, tested at `lastIndex = j`. */
  readonly tail: RegExp;
  /** Bounded-depth whole-line regex, or null. */
  readonly fast: Matcher | null;
  /** The fast answer that is final; the other one runs the split path. */
  readonly fastFinal: FastFinal;
}

const isLowSurrogate = (c: number): boolean => c >= 0xdc00 && c <= 0xdfff;
const isHighSurrogate = (c: number): boolean => c >= 0xd800 && c <= 0xdbff;

/** `HEAD leaf TAIL` over the whole line, with a bounded-depth fast path. */
export class SplitMatcher implements Matcher {
  readonly #parts: SplitParts;

  constructor(parts: SplitParts) {
    this.#parts = parts;
  }

  test(text: string, deadline: Deadline): boolean {
    const { fast, fastFinal } = this.#parts;
    if (fast !== null) {
      const answer = fast.test(text, deadline);
      if (answer === (fastFinal === FAST_ACCEPT)) return answer;
    }
    return this.#splitPath(text, deadline);
  }

  #splitPath(text: string, deadline: Deadline): boolean {
    for (let i = 0; i <= text.length; i += 1) {
      if (this.#splitsAfterHead(text, i, deadline)) return true;
    }
    return false;
  }

  #splitsAfterHead(text: string, i: number, deadline: Deadline): boolean {
    const { head, ends, tail } = this.#parts;
    // A head cannot end inside a surrogate pair: Python positions are code points.
    if (isLowSurrogate(text.charCodeAt(i)) && isHighSurrogate(text.charCodeAt(i - 1))) {
      return false;
    }
    head.lastIndex = i;
    if (!deadline.test(head, text)) return false;
    deadline.check();
    for (const j of ends(text, i)) {
      tail.lastIndex = j;
      if (deadline.test(tail, text)) return true;
    }
    return false;
  }
}
