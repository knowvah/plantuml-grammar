import { describe, expect, it, vi } from "vitest";
import { Deadline } from "../src/deadline.js";
import { JOINER, scanBracket, scanJoin, scanMultiline, unitEnd } from "../src/scan.js";
import type { Join } from "../src/scan.js";
import { RegexMatcher } from "../src/matcher.js";
import { lines } from "./helpers/engine.js";

const UNCAPPED = 100_000;
const BUDGET_MS = 10_000;
const STYLE = new RegExp(`^<style>(?:${JOINER}[a-z]+)*${JOINER}</style>$`, "u");
const STYLE_PREFIX = new RegExp(`^<style>(?:${JOINER}[a-z]+)*${JOINER}(?:</style>)?$`, "u");
const END = new RegexMatcher(/^end$/u);

const join = (over: Partial<Join> = {}): Join => ({
  start: new RegexMatcher(STYLE),
  prefix: new RegexMatcher(STYLE_PREFIX),
  maxLines: UNCAPPED,
  glueUnits: true,
  ...over,
});

describe("unitEnd", () => {
  const body = lines("a", "{{", "x", "{{", "y", "}}", "}}", "b");
  it("is one line without an embedded start", () => {
    expect(unitEnd(body, 0)).toBe(1);
  });
  it("glues nested embedded diagrams", () => {
    expect(unitEnd(body, 1)).toBe(7);
  });
  it("swallows the rest when unterminated", () => {
    expect(unitEnd(lines("{{", "a", "b"), 0)).toBe(3);
  });
  it("treats every line as a unit without glue", () => {
    expect(unitEnd(body, 1, false)).toBe(2);
  });
});

describe("scanMultiline", () => {
  it("never accepts a single line and tests the last line of later units", () => {
    expect(scanMultiline(END, lines("start", "end"), 0, new Deadline(BUDGET_MS))).toBe(2);
    expect(scanMultiline(END, lines("end"), 0, new Deadline(BUDGET_MS))).toBeNull();
  });
  it("returns null when no end appears", () => {
    expect(scanMultiline(END, lines("s", "a", "b"), 0, new Deadline(BUDGET_MS))).toBeNull();
  });
  it("treats a glued group as one unit", () => {
    const body = lines("s", "{{", "end", "}}", "end");
    expect(scanMultiline(END, body, 0, new Deadline(BUDGET_MS))).toBe(5);
    expect(scanMultiline(END, body, 0, new Deadline(BUDGET_MS), false)).toBe(3);
  });
});

describe("scanBracket", () => {
  it("returns the index when depth returns to zero", () => {
    expect(scanBracket(lines("a {", "b {", "}", "}"), 0)).toBe(4);
  });
  it("returns null when depth goes below zero", () => {
    expect(scanBracket(lines("a {", "{{", "}", "}", "}}"), 0)).toBeNull();
  });
  it("returns null when never closed", () => {
    expect(scanBracket(lines("a {", "b"), 0)).toBeNull();
  });
  it("counts a glued group's lines before deciding, unlike separate units", () => {
    const body = lines("a {", "{{", "}", "}", "}}");
    expect(scanBracket(body, 0)).toBeNull();
    expect(scanBracket(body, 0, false)).toBe(4);
  });
});

describe("scanJoin", () => {
  it("stops after one start test and one prefix test when the prefix rejects", () => {
    const deadline = new Deadline(BUDGET_MS);
    const spy = vi.spyOn(deadline, "test");
    const body = lines("class A", ...Array<string>(5000).fill("line"));
    expect(scanJoin(join(), body, 0, deadline)).toBeNull();
    expect(spy).toHaveBeenCalledTimes(2);
    expect(spy.mock.calls[0]?.[0]).toBe(STYLE);
    expect(spy.mock.calls[1]?.[0]).toBe(STYLE_PREFIX);
  });
  it("finds the smallest matching k", () => {
    const body = lines("<style>", "a", "b", "</style>", "after");
    expect(scanJoin(join(), body, 0, new Deadline(BUDGET_MS))).toBe(4);
  });
  it("respects the line cap", () => {
    const body = lines("<style>", "a", "b", "</style>");
    expect(scanJoin(join({ maxLines: 2 }), body, 0, new Deadline(BUDGET_MS))).toBeNull();
    expect(scanJoin(join({ maxLines: 3 }), body, 0, new Deadline(BUDGET_MS))).toBe(4);
  });
  it("returns null when lines run out", () => {
    expect(scanJoin(join(), lines("<style>", "a"), 0, new Deadline(BUDGET_MS))).toBeNull();
  });
  it("never stops early without a prefix pattern", () => {
    const body = lines("x", "y", "z");
    const deadline = new Deadline(BUDGET_MS);
    const spy = vi.spyOn(deadline, "test");
    expect(scanJoin(join({ prefix: null }), body, 0, deadline)).toBeNull();
    expect(spy).toHaveBeenCalledTimes(3);
  });
  it("glues embedded groups only with glueUnits", () => {
    const body = lines("<style>", "{{", "a", "</style>", "tail");
    expect(scanJoin(join(), body, 0, new Deadline(BUDGET_MS))).toBeNull();
    expect(scanJoin(join({ glueUnits: false }), lines("<style>", "{{", "a", "</style>"), 0, new Deadline(BUDGET_MS))).toBeNull();
    expect(scanJoin(join({ glueUnits: false, start: /^<style>\{\{a<\/style>$/u, prefix: null }), lines("<style>", "{{", "a", "</style>"), 0, new Deadline(BUDGET_MS))).toBe(4);
  });
});
