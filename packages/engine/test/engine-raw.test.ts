// Ports tests/interp/test_raw.py to the TypeScript interpreter; see helpers/engine-fixtures.ts.
import { describe, expect, it } from "vitest";
import { Interpreter, accepts, loadEngine } from "../src/index.js";
import { failureOf, load, readJson, uml } from "./helpers/engine-fixtures.js";

const toys = load("toys");

describe("raw mode (test_raw.py)", () => {
  it("ignores preproc lines unless raw", () => {
    const text = uml("!define X 1", "alpha x");
    expect(failureOf(accepts(toys, text))).toEqual([2, "!define X 1"]);
    const raw = accepts(toys, text, { raw: true });
    expect([raw.accepted, raw.model]).toEqual([true, "seqtoy"]);
  });

  it("consumes a preproc multiline body", () => {
    const text = uml("!procedure p()", "]]] not a command", "!endprocedure", "alpha x");
    expect(accepts(toys, text, { raw: true }).accepted).toBe(true);
  });

  it("follows diagram-rule semantics for push, set and pop", () => {
    expect(accepts(toys, uml("!if A", "alpha a", "!else", "alpha b", "!endif", "alpha c"), { raw: true }).accepted).toBe(true);
    expect(failureOf(accepts(toys, uml("!else"), { raw: true }))).toEqual([2, "!else"]);
    expect(failureOf(accepts(toys, uml("!if A", "!else", "!else"), { raw: true }))).toEqual([4, "!else"]);
    expect(failureOf(accepts(toys, uml("!if A", "!if B", "!endif"), { raw: true }))).toEqual([3, "!if B"]);
  });

  it("starts the preproc stack at main for every factory attempt", () => {
    const v = accepts(toys, uml("!if A", "beta y"), { raw: true });
    expect([v.accepted, v.model]).toEqual([true, "classtoy"]);
  });

  it("treats a block of only preproc lines as an empty diagram", () => {
    const v = accepts(toys, uml("!define X 1"), { raw: true });
    expect([v.accepted, v.status]).toEqual([false, "reject"]);
    expect(failureOf(v)).toEqual([1, "@startuml"]);
  });

  it("behaves like preprocessed input without a preproc model", () => {
    const json = readJson("toys") as { models: Record<string, unknown>; model_order: string[] };
    delete json.models["preproctoy"];
    json.model_order = json.model_order.filter((id) => id !== "preproctoy");
    const without = loadEngine(json);
    expect(failureOf(accepts(without, uml("!define X 1"), { raw: true }))).toEqual([2, "!define X 1"]);
    expect(accepts(without, uml("alpha x"), { raw: true }).accepted).toBe(true);
  });

  it("runs the preproc filter once per block, not once per factory attempt", () => {
    // Clock reads count regex calls. Trying seqtoy as well as classtoy costs the same
    // extra reads whatever the number of preproc lines, so the filter is not re-run.
    const reads = (preprocLines: number, startMap: string[]): number => {
      let calls = 0;
      const clock = (): number => (calls += 1);
      const defines = Array.from({ length: preprocLines }, (_, n) => `!define V${n} 1`);
      new Interpreter(toys, { clock, startMap: { uml: startMap } }).accepts(
        uml(...defines, "beta y"),
        { raw: true },
      );
      return calls;
    };
    const extra = (n: number): number => reads(n, ["seqtoy", "classtoy"]) - reads(n, ["classtoy"]);
    expect(extra(1)).toBeGreaterThan(0);
    expect(extra(3)).toBe(extra(1));
  });
});

