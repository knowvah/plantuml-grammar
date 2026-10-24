import { describe, expect, it } from "vitest";
import { jsonBlockBodyEnds, jsonDataInvalidEnds } from "../src/native.js";

const J = "";
const DEEP = 100;
const VERY_DEEP = 200_000;
const DEEP_BUDGET_MS = 50;
const nested = (k: number, inner = "1"): string => "[".repeat(k) + inner + "]".repeat(k);

describe("jsonBlockBodyEnds scalars", () => {
  it.each([
    ["", [0]],
    ["1", [0, 1]],
    ["12", [0, 1, 2]],
    ["01", [0, 1]],
    ["-0", [0, 2]],
    ["-", [0]],
    ["0.5", [0, 1, 3]],
    ["1.", [0, 1]],
    ["1.5.5", [0, 1, 3]],
    ["1e5", [0, 1, 3]],
    ["1E+5", [0, 1, 4]],
    ["1e-", [0, 1]],
    ["1e", [0, 1]],
    ["true", [0, 4]],
    ["tru", [0]],
    ["True", [0]],
    ["false", [0, 5]],
    ["null", [0, 4]],
    ["nul", [0]],
    ['"a"', [0, 3]],
    ['"a', [0]],
    ["x", [0]],
  ])("%j -> %j", (s, ends) => {
    expect(jsonBlockBodyEnds(s, 0)).toEqual(ends);
  });

  it("reports ends relative to the start offset", () => {
    expect(jsonBlockBodyEnds("xx12", 2)).toEqual([2, 3, 4]);
  });
});

describe("jsonBlockBodyEnds joiner and whitespace", () => {
  it.each([
    [" 1 ", [0, 1, 2, 3]],
    [`${J}1`, [0, 1, 2]],
    [`-${J}1`, [0, 3]],
    [`1${J}${J}.${J}5`, [0, 1, 2, 3, 6]],
    [`1${J}e${J}+${J}5`, [0, 1, 2, 7]],
    [`t${J}r${J}u${J}e`, [0, 7]],
    [`t${J}${J}rue`, [0, 6]],
    [`[${J}1${J},${J}2${J}]`, [0, 9]],
    ["[\t1\r\n,2]", [0, 8]],
  ])("%j -> %j", (s, ends) => {
    expect(jsonBlockBodyEnds(s, 0)).toEqual(ends);
  });
});

describe("jsonBlockBodyEnds strings", () => {
  it.each([
    ['"\\"\\\\\\/\\b\\f\\n\\r\\t\\u00Af"', true],
    ['"\\x"', false],
    ['"\\u12G4"', false],
    ['"\\u12"', false],
    ['"\\', false],
    ['"a\tb"', false],
    ['"a\nb"', false],
    [`"a${J}b"`, true],
    ['"é中😀"', true],
  ])("%j accepted=%j", (s, accepted) => {
    expect(jsonBlockBodyEnds(s, 0).includes(s.length)).toBe(accepted);
  });
});

describe("jsonBlockBodyEnds containers", () => {
  it.each([
    ["[]", [0, 2]],
    ["[ ]", [0, 3]],
    ["{}", [0, 2]],
    ["{ }", [0, 3]],
    ["[1,2]", [0, 5]],
    ["[1,]", [0]],
    ["[,1]", [0]],
    ["[1 2]", [0]],
    ["[1", [0]],
    ["[}", [0]],
    ["{]", [0]],
    ["[1)", [0]],
    ["[]]", [0, 2]],
    ['{"a":1}', [0, 7]],
    ['{"a" : 1 , "b" : [1, 2]}', [0, 24]],
    ['{"a":1,}', [0]],
    ['{"a"}', [0]],
    ["{a:1}", [0]],
    ['{"a":}', [0]],
    ['{"a":1 "b":2}', [0]],
    ['{"a\\x":1}', [0]],
    ['{"a":[1,{"b":null}]}', [0, 20]],
  ])("%j -> %j", (s, ends) => {
    expect(jsonBlockBodyEnds(s, 0)).toEqual(ends);
  });

  it("accepts a member list without braces, at every pair boundary", () => {
    expect(jsonBlockBodyEnds('"a":1,"b":2', 0)).toEqual([0, 3, 5, 11]);
    expect(jsonBlockBodyEnds('"a":1 , "b" : 22 ', 0)).toEqual([0, 3, 5, 6, 15, 16, 17]);
    expect(jsonBlockBodyEnds('"a":1,', 0)).toEqual([0, 3, 5]);
    expect(jsonBlockBodyEnds('"a" 1', 0)).toEqual([0, 3, 4]);
    expect(jsonBlockBodyEnds('"a\\x":1', 0)).toEqual([0]);
    expect(jsonBlockBodyEnds('"a":', 0)).toEqual([0, 3]);
  });

  it("stops a member list at the first pair that is not followed by a comma", () => {
    expect(jsonBlockBodyEnds('"a":12', 0)).toEqual([0, 3, 5, 6]);
  });
});

describe("jsonBlockBodyEnds depth", () => {
  it(`handles ${DEEP} levels quickly`, () => {
    const s = nested(DEEP);
    const started = performance.now();
    const ends = jsonBlockBodyEnds(s, 0);
    expect(performance.now() - started).toBeLessThan(DEEP_BUDGET_MS);
    expect(ends).toEqual([0, s.length]);
  });

  it("handles nesting far beyond any call stack, objects and arrays mixed", () => {
    const open = '[{"a":'.repeat(VERY_DEEP / 2);
    const close = "}]".repeat(VERY_DEEP / 2);
    const s = `${open}1${close}`;
    expect(jsonBlockBodyEnds(s, 0)).toEqual([0, s.length]);
    expect(jsonBlockBodyEnds(s.slice(0, -1), 0)).toEqual([0]);
  });

  it("rejects unbalanced deep input", () => {
    expect(jsonBlockBodyEnds(nested(DEEP).slice(1), 0)).toEqual([0, 2 * DEEP - 1]);
    expect(jsonBlockBodyEnds(nested(DEEP).slice(0, -1), 0)).toEqual([0]);
    expect(jsonBlockBodyEnds(nested(DEEP, "1,"), 0)).toEqual([0]);
  });
});

describe("jsonDataInvalidEnds valid data is excluded", () => {
  it.each([
    "true",
    "false",
    "null",
    "0",
    "-0",
    "123",
    '"a"',
    '"a\\"b"',
    "[1,[2]]",
    '{"a":1}',
    '{"a":{"b":[]}}',
    "true\n",
    "null\x85",
    '"a"\r',
    "[1] ",
    '{"a":1} ',
  ])("%j has no ends", (s) => {
    expect(jsonDataInvalidEnds(s, 0)).toEqual([]);
  });
});

describe("jsonDataInvalidEnds invalid data", () => {
  it.each([
    ["TRUE", [4]],
    ["tRuE", [4]],
    ["NULL", [4]],
    ["False", [5]],
    ["nUll\n", [4]],
    ["012", [1, 2, 3]],
    ["-012", [2, 3, 4]],
    ["-", []],
    ["x", []],
    ["", []],
    ["tru", []],
    ['"a\\x"', [5]],
    ['"a"b"', [3, 5]],
    ['"a\nb"', []],
    ["[1,]", [4]],
    ["[1]x]", [3, 5]],
    ["[a]\n]", [3]],
    ["{}", []],
    ['{“a”:"x"}', [9]],
    ["{a:1}", []],
    ["{\ue121a\ue121:1}", [7]],
    ['{"a":x}', [7]],
    ['{"a":1}x', [7]],
    ['{"a":1}}', [7, 8]],
    ["{“a”:x}", [7]],
    ['{"a\\":1}', [8]],
    ['{"a\\"":x}', [9]],
    ['{ "a" : x}', [10]],
    ['{ "a" : x }', [11]],
    ['{"":x}', []],
    ['{"a" x}', []],
    ['{"a":x\n}', []],
    ['{"a"\n:x}', [8]],
    ['{"\\":x}', [7]],
    ['{"a":"b}"', [8]],
    ["{“abc”: x}", [10]],
    ["[1,2\n]", []],
  ])("%j -> %j", (s, ends) => {
    expect(jsonDataInvalidEnds(s, 0)).toEqual(ends);
  });

  it("deals with deep nesting without recursion", () => {
    expect(jsonDataInvalidEnds(nested(VERY_DEEP), 0)).toEqual([]);
    const broken = nested(VERY_DEEP, "1,");
    const ends = jsonDataInvalidEnds(broken, 0);
    expect([ends.length, ends[0], ends.at(-1)]).toEqual([VERY_DEEP, VERY_DEEP + 3, broken.length]);
  });

  it("reports ends relative to the start offset", () => {
    expect(jsonDataInvalidEnds("--TRUE", 2)).toEqual([6]);
  });
});
