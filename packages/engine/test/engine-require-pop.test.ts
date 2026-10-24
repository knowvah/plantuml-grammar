// Ports tests/interp/test_require_pop_reject.py to the TypeScript interpreter; see helpers/engine-fixtures.ts.
import { describe, expect, it } from "vitest";
import { accepts } from "../src/index.js";
import { load, only, runner, uml } from "./helpers/engine-fixtures.js";

describe("require_pop and reject (test_require_pop_reject.py)", () => {
  const run = runner(load("require-pop"));

  it("accepts an unterminated body without require_pop", () => {
    expect(run("rp-plain", "open {", "a", "b")).toEqual([true, null]);
  });

  it("rejects an unterminated body at the pushing line", () => {
    expect(run("rp-open", "ok", "open {", "a", "b")).toEqual([false, [3, "open {"]]);
  });

  it("accepts a terminated body", () => {
    expect(run("rp-open", "open {", "a", "}", "c")).toEqual([true, null]);
  });

  it("rejects when the body ends right after the push", () => {
    expect(run("rp-open", "open {")).toEqual([false, [2, "open {"]]);
  });

  it("backtracks to a later candidate at the pushing line", () => {
    expect(run("rp-fallback", "open {", "a", "b")).toEqual([true, null]);
  });

  it("resumes in the context of the pushing line", () => {
    expect(run("rp-fallback", "open {", "inner {", "x", "}")).toEqual([false, [3, "inner {"]]);
  });

  it("reports the pushing line when the later candidate also fails", () => {
    expect(run("rp-nope", "open {", "a")).toEqual([false, [2, "open {"]]);
  });

  it("backtracks to the outer line when the outer frame is unclosed", () => {
    expect(run("rp-open", "open {", "inner {", "x", "}")).toEqual([false, [2, "open {"]]);
    expect(run("rp-open", "open {", "inner {", "x", "}", "}")).toEqual([true, null]);
  });

  it("fails at the outermost open line for an unclosed inner frame", () => {
    expect(run("rp-open", "open {", "inner {", "x")).toEqual([false, [2, "open {"]]);
  });

  it("does not backtrack over closed frames", () => {
    expect(run("rp-open", "open {", "}", "open {", "a")).toEqual([false, [4, "open {"]]);
  });

  it("keeps frames aligned across a pop on the bottom context", () => {
    expect(run("rp-bottom", "p", "open {", "}")).toEqual([true, null]);
    expect(run("rp-bottom", "p", "open {")).toEqual([false, [3, "open {"]]);
  });

  it("keeps the open frame marker across a set", () => {
    expect(run("rp-set", "open {", "sw", "}")).toEqual([true, null]);
    expect(run("rp-set", "open {", "sw")).toEqual([false, [2, "open {"]]);
  });

  it("lets a catch-all swallow the line without reject", () => {
    expect(run("rj-catch", "page 0")).toEqual([true, null]);
  });

  it("stops fall-through to a later catch-all on reject", () => {
    expect(run("rj-reject", "x", "page 0")).toEqual([false, [3, "page 0"]]);
  });

  it("leaves other lines to later entries", () => {
    expect(run("rj-reject", "page 3", "anything")).toEqual([true, null]);
  });

  it("applies reject only when selected first", () => {
    expect(run("rj-later", "page 0")).toEqual([true, null]);
  });

  it("rejects inside a pushed context", () => {
    expect(run("rj-body", "open {", "ok", "bad", "}")).toEqual([false, [4, "bad"]]);
  });

  it("rejects via insert_before over an unnarrowed rule", () => {
    const engine = load("require-pop");
    const zero = accepts(engine, uml("page 0"), only("rj-top"));
    expect([zero.accepted, zero.model]).toEqual([false, null]);
    expect(accepts(engine, uml("page 1"), only("rj-top")).model).toBe("rj-top");
  });

  it.each([[["page 0"]], [["x", "page 0"]]])("fails reject at the first failure line for %j", (lines) => {
    expect(run("rj-first", ...lines)).toEqual([false, [lines.length + 1, "page 0"]]);
  });
});

