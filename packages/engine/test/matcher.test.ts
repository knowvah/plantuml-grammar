import { describe, expect, it, vi } from "vitest";
import { BlockTimeout, Deadline } from "../src/deadline.js";
import { NATIVE_KINDS, AnyMatcher, RegexMatcher, SplitMatcher } from "../src/matcher.js";
import type { NativeEnds, SplitParts } from "../src/matcher.js";
import { jsonBlockBodyEnds } from "../src/native.js";
import type { PatternJson } from "../src/types.js";
import { engineJson, entry } from "./helpers/engine.js";

const BUDGET_MS = 10_000;
const fresh = (): Deadline => new Deadline(BUDGET_MS);
const sticky = (source: string): RegExp => new RegExp(source, "uy");
const whole = (source: string): RegexMatcher => new RegexMatcher(new RegExp(source, "u"));
const DEEP = 60;
const deepArray = "[".repeat(DEEP) + "1" + "]".repeat(DEEP);

function parts(over: Partial<SplitParts> & { ends?: NativeEnds } = {}): SplitParts {
  return {
    head: sticky("(?<=^(?:data: ))"),
    ends: jsonBlockBodyEnds,
    tail: sticky(";$"),
    fast: whole("^data: (?:\\[\\]|\\[1\\]);$"),
    fastFinal: "accept",
    ...over,
  };
}

describe("RegexMatcher and AnyMatcher", () => {
  it("regex tests the line through the deadline", () => {
    const deadline = fresh();
    const spy = vi.spyOn(deadline, "test");
    expect(whole("^a$").test("a", deadline)).toBe(true);
    expect(whole("^a$").test("b", deadline)).toBe(false);
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("any is true when one member matches and stops at the first", () => {
    const deadline = fresh();
    const spy = vi.spyOn(deadline, "test");
    const any = new AnyMatcher([whole("^a$"), whole("^b$"), whole("^c$")]);
    expect(any.test("b", deadline)).toBe(true);
    expect(spy).toHaveBeenCalledTimes(2);
    expect(any.test("z", fresh())).toBe(false);
    expect(new AnyMatcher([]).test("a", fresh())).toBe(false);
  });
});

describe("SplitMatcher fast path, fast_final accept", () => {
  it("never calls the native leaf when the fast regex matches", () => {
    const ends = vi.fn(jsonBlockBodyEnds);
    const deadline = fresh();
    const spy = vi.spyOn(deadline, "test");
    expect(new SplitMatcher(parts({ ends })).test("data: [1];", deadline)).toBe(true);
    expect(ends).not.toHaveBeenCalled();
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("falls through to the split path when the fast regex rejects", () => {
    const ends = vi.fn(jsonBlockBodyEnds);
    const matcher = new SplitMatcher(parts({ ends }));
    expect(matcher.test(`data: ${deepArray};`, fresh())).toBe(true);
    expect(ends).toHaveBeenCalledWith(`data: ${deepArray};`, 6);
    expect(matcher.test(`data: ${deepArray.slice(1)};`, fresh())).toBe(false);
    expect(matcher.test("data: [1]x", fresh())).toBe(false);
  });
});

describe("SplitMatcher fast path, fast_final reject", () => {
  const rejecting = (ends: NativeEnds): SplitParts =>
    parts({ ends, fast: whole("^data: .*$"), fastFinal: "reject" });

  it("never calls the native leaf when the fast regex rejects", () => {
    const ends = vi.fn(jsonBlockBodyEnds);
    expect(new SplitMatcher(rejecting(ends)).test("other: 1;", fresh())).toBe(false);
    expect(ends).not.toHaveBeenCalled();
  });

  it("falls through to the split path when the fast regex matches", () => {
    const ends = vi.fn(jsonBlockBodyEnds);
    const matcher = new SplitMatcher(rejecting(ends));
    expect(matcher.test("data: [1];", fresh())).toBe(true);
    expect(matcher.test("data: [1,];", fresh())).toBe(false);
    expect(ends).toHaveBeenCalledTimes(2);
  });
});

describe("SplitMatcher split path", () => {
  it("runs without a fast regex", () => {
    const matcher = new SplitMatcher(parts({ fast: null }));
    expect(matcher.test("data: [1];", fresh())).toBe(true);
    expect(matcher.test("data: [1]", fresh())).toBe(false);
    expect(matcher.test("", fresh())).toBe(false);
  });

  it("lets the lookbehind head see the real text after the split point", () => {
    const head = sticky("(?<=^(?:x(?!1)))");
    const matcher = new SplitMatcher(parts({ head, tail: sticky("$"), fast: null }));
    expect(matcher.test("x2", fresh())).toBe(true);
    // A sliced string would see "x" and accept; the whole line sees the 1 and rejects.
    expect(matcher.test("x1", fresh())).toBe(false);
    const slicedHead = sticky("(?<=^(?:x(?!1)))");
    slicedHead.lastIndex = 1;
    expect(slicedHead.test("x")).toBe(true);
  });

  it("tries every head position and every native end", () => {
    const ends = vi.fn((_s: string, i: number) => (i === 1 ? [1, 2, 3] : []));
    const tail = sticky("c$");
    const matcher = new SplitMatcher(
      parts({ head: sticky("(?<=^a)"), ends, tail, fast: null }),
    );
    expect(matcher.test("abc", fresh())).toBe(true);
    expect(ends.mock.calls.map(([, i]) => i)).toEqual([1]);
  });

  it("does not start a head inside a surrogate pair", () => {
    const ends = vi.fn((_s: string, _i: number): number[] => []);
    const matcher = new SplitMatcher(parts({ head: sticky(""), ends, fast: null }));
    expect(matcher.test("a\u{1f600}", fresh())).toBe(false);
    // Positions 0, 1 and 3 only; 2 is the middle of the pair.
    expect(ends.mock.calls).toEqual([["a\u{1f600}", 0], ["a\u{1f600}", 1], ["a\u{1f600}", 3]]);
  });
});

describe("SplitMatcher deadline", () => {
  it("throws before any native call when the budget is already spent", () => {
    const ends = vi.fn(jsonBlockBodyEnds);
    const spent = new Deadline(0);
    const matcher = new SplitMatcher(parts({ ends, fast: null }));
    expect(() => matcher.test("data: [1];", spent)).toThrow(BlockTimeout);
    expect(ends).not.toHaveBeenCalled();
    expect(() => new SplitMatcher(parts({ ends })).test("data: [1];", spent)).toThrow(BlockTimeout);
  });

  it("checks the deadline again before the native call", () => {
    const ends = vi.fn(jsonBlockBodyEnds);
    const clock = vi.fn().mockReturnValueOnce(0).mockReturnValueOnce(0).mockReturnValue(BUDGET_MS * 2);
    const deadline = new Deadline(BUDGET_MS, clock);
    const matcher = new SplitMatcher(parts({ ends, fast: null }));
    expect(() => matcher.test("data: [1];", deadline)).toThrow(BlockTimeout);
    expect(ends).not.toHaveBeenCalled();
  });
});

describe("matcher(id) from engine JSON", () => {
  const patterns: PatternJson[] = [
    { source: "^data: (?:\\[\\]|\\[1\\]);$", flags: "u" },
    { source: "(?<=^(?:data: ))", flags: "uy" },
    { source: ";$", flags: "uy" },
    { split: { head: 1, native: "json-block-body", tail: 2, fast: 0, fast_final: "accept" } },
    { source: "^plain$", flags: "u" },
    { any: [3, 4] },
    { source: "^val: .*$", flags: "u" },
    { source: "(?<=^(?:val: ))", flags: "uy" },
    { source: "$", flags: "uy" },
    { split: { head: 7, native: "json-data-invalid", tail: 8, fast: 6, fast_final: "reject" } },
  ];
  const engine = engineJson(patterns, [entry({ start: 3 })]);

  it("builds a split that decides deep input natively", () => {
    expect(engine.matcher(3).test(`data: ${deepArray};`, fresh())).toBe(true);
    expect(engine.matcher(3).test("data: [2,];", fresh())).toBe(false);
  });

  it("builds an any over a split and a plain regex, cached per id", () => {
    expect(engine.matcher(5).test("plain", fresh())).toBe(true);
    expect(engine.matcher(5).test(`data: ${deepArray};`, fresh())).toBe(true);
    expect(engine.matcher(5).test("nope", fresh())).toBe(false);
    expect(engine.matcher(5)).toBe(engine.matcher(5));
  });

  it("builds the data-invalid split with the reject-final fast regex", () => {
    expect(engine.matcher(9).test("val: TRUE", fresh())).toBe(true);
    expect(engine.matcher(9).test("val: true", fresh())).toBe(false);
    expect(engine.matcher(9).test("other", fresh())).toBe(false);
  });

  it("uses the registered native leaves", () => {
    expect(Object.keys(NATIVE_KINDS)).toEqual(["json-block-body", "json-data-invalid"]);
  });
});
