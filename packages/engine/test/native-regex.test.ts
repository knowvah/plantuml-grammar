import { describe, expect, it } from "vitest";
import { regexWellFormedEnds } from "../src/native-regex.js";

const wellFormed = (s: string): boolean => regexWellFormedEnds(s, 0).includes(s.length);
const DEEP = 5000;

describe("regexWellFormedEnds operands", () => {
  it("accepts literals, anchors, dots and escapes", () => {
    for (const s of ["a", "ab", "^a$", ".", "\\d", "\\.", "\\0123", "\\u00e9", "\\p{L}", "\\x{41}"]) {
      expect(wellFormed(s), s).toBe(true);
    }
  });

  it("rejects short or line-broken escapes and a trailing backslash", () => {
    for (const s of ["\\012", "\\u00e", "\\p{L", "\\", "\\0a\nb", "a\\"]) {
      expect(wellFormed(s), JSON.stringify(s)).toBe(false);
    }
  });

  it("handles classes, posix classes and an unclosed class at the line end", () => {
    expect(wellFormed("[ab]")).toBe(true);
    expect(wellFormed("[\\]]")).toBe(true);
    expect(wellFormed("[[:alpha:]]")).toBe(true);
    expect(wellFormed("[ab")).toBe(true);
    expect(wellFormed("[ab\n")).toBe(true);
    expect(wellFormed("[ab\r\nx")).toBe(true); // the class swallows the terminators too
    expect(wellFormed("[ab\r\n\n")).toBe(true);
    expect(wellFormed("[]")).toBe(false);
    expect(wellFormed("[[:al")).toBe(false);
    expect(wellFormed("[a\\")).toBe(false);
  });

  it("treats operator characters alone as not well formed", () => {
    for (const s of ["*", "|", "(", ")", "{2}", "?", "a|", "|a", "(a|)", "(?i)a"]) {
      expect(wellFormed(s), s).toBe(false);
    }
  });
});

describe("regexWellFormedEnds groups and quantifiers", () => {
  it("accepts groups, lookarounds, named groups and comments", () => {
    for (const s of ["(a)", "(a|b)", "(?:a)", "(?=a)", "(?!a)", "(?<=a)b", "(?<n>a)", "(?#c)a(?#d)"]) {
      expect(wellFormed(s), s).toBe(true);
    }
  });

  it("rejects unbalanced groups and an unclosed comment", () => {
    for (const s of ["(a", "a)", "((a)", "(a))", "(?#c", "(?<>a)", "(?<n1>a)", "()"]) {
      expect(wellFormed(s), s).toBe(false);
    }
  });

  it("accepts quantifier chains the lexer takes one at a time", () => {
    for (const s of ["a*", "a*?", "a*??", "a+?", "a{2}", "a{2,}", "a{,}", "a{2}{3}", "a{2}(?#c){3}"]) {
      expect(wellFormed(s), s).toBe(true);
    }
    for (const s of ["a{2}?", "a{}", "a{2", "a{x}"]) {
      expect(wellFormed(s), s).toBe(false);
    }
  });

  it("ends the line at a NUL and ignores what follows", () => {
    expect(regexWellFormedEnds("a\0junk )(", 0)).toEqual([9]);
    expect(regexWellFormedEnds("a\0junk\nmore", 0)).toEqual([6]);
    expect(wellFormed("(a\0)")).toBe(false);
  });

  it("counts an astral character as one escape char but not as a group name", () => {
    expect(wellFormed("\\0𝐀bc")).toBe(true);
    expect(wellFormed("𝐀+")).toBe(true);
    expect(wellFormed("(?<é>a)")).toBe(true);
    expect(wellFormed("(?<𝐀>a)")).toBe(false);
  });

  it("reports ends relative to the start offset", () => {
    expect(regexWellFormedEnds("  (a)", 2)).toEqual([5]);
    expect(regexWellFormedEnds("  (a", 2)).toEqual([]);
  });

  it(`nests ${DEEP} groups`, () => {
    const s = "(".repeat(DEEP) + "a" + ")".repeat(DEEP);
    expect(wellFormed(s)).toBe(true);
    expect(wellFormed(s.slice(0, -1))).toBe(false);
  });
});
