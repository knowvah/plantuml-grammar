import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import {
  EngineFormatError,
  loadEngine,
  ModelError,
  UnknownContextError,
} from "../src/load.js";

function fixture(name: string): Record<string, any> { // eslint-disable-line -- test-only JSON poking
  return JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));
}
const tiny = (): Record<string, any> => fixture("tiny.engine.json"); // eslint-disable-line

function pointerOf(json: unknown): string {
  try {
    loadEngine(json);
  } catch (err) {
    if (err instanceof EngineFormatError) return err.pointer;
    throw err;
  }
  return "no-throw";
}

describe("loadEngine happy path", () => {
  it("exposes counts, models in model_order and tops", () => {
    const m = loadEngine(tiny());
    expect(m.patternCount).toBe(5);
    expect(m.compiledCount).toBe(0);
    expect([...m.models.keys()]).toEqual(["alpha", "beta"]);
    expect(m.tops).toEqual({ F: "alpha" });
  });

  it("honours model_order rather than key order", () => {
    const j = tiny();
    j["model_order"] = ["beta", "alpha"];
    expect([...loadEngine(j).models.keys()]).toEqual(["beta", "alpha"]);
  });

  it("returns context entries including the join prefix", () => {
    const m = loadEngine(tiny());
    const entries = m.context("alpha", "extra");
    expect(entries).toHaveLength(1);
    expect(entries[0]?.join).toEqual({ max_lines: 50, prefix: 4 });
  });

  it("throws UnknownContextError for missing model or context", () => {
    const m = loadEngine(tiny());
    expect(() => m.context("alpha", "nope")).toThrow(UnknownContextError);
    expect(() => m.context("zzz", "main")).toThrow(/zzz/);
  });
});

describe("pattern compilation", () => {
  it("compiles once and returns the same instance", () => {
    const compile = vi.fn((s: string, f: string) => new RegExp(s, f));
    const m = loadEngine(tiny(), { compile });
    const first = m.pattern(3);
    expect(m.pattern(3)).toBe(first);
    expect(compile).toHaveBeenCalledTimes(1);
    expect(compile).toHaveBeenCalledWith("^(?:c)$", "u");
    expect(m.compiledCount).toBe(1);
    expect(first.test("c")).toBe(true);
  });

  it("uses RegExp with flag u by default", () => {
    expect(loadEngine(tiny()).pattern(0).flags).toBe("u");
  });

  it("throws ModelError with the reason for unsupported patterns", () => {
    const m = loadEngine(tiny());
    expect(() => m.pattern(2)).toThrow(ModelError);
    expect(() => m.pattern(2)).toThrow("recursion depth exceeds 256 KB");
    expect(m.compiledCount).toBe(0);
  });

  it("wraps compile failures with the SyntaxError as cause", () => {
    const j = tiny();
    j["patterns"][0] = { source: "(", flags: "u" };
    const m = loadEngine(j);
    let caught: unknown;
    try {
      m.pattern(0);
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ModelError);
    expect((caught as ModelError).cause).toBeInstanceOf(SyntaxError);
    expect((caught as ModelError).message).toContain("pattern 0");
  });

  it("rejects out-of-range pattern ids at use", () => {
    expect(() => loadEngine(tiny()).pattern(99)).toThrow(RangeError);
  });
});

describe("loadEngine validation", () => {
  it("rejects non-objects at the root", () => {
    expect(pointerOf(null)).toBe("");
    expect(pointerOf([])).toBe("");
  });

  it("rejects engine_format 2 (fixture) naming /engine_format", () => {
    expect(pointerOf(fixture("bad-format.engine.json"))).toBe("/engine_format");
  });

  it("rejects a context index out of range", () => {
    const j = tiny();
    j["models"]["alpha"]["contexts"]["main"] = 9;
    expect(pointerOf(j)).toBe("/models/alpha/contexts/main");
  });

  it("escapes pointer tokens", () => {
    const j = tiny();
    j["models"]["a/b"] = structuredClone(j["models"]["alpha"]);
    j["models"]["a/b"]["contexts"]["x~y"] = 9;
    j["model_order"].push("a/b");
    expect(pointerOf(j)).toBe("/models/a~1b/contexts/x~0y");
  });

  it("rejects a pattern id out of range in an entry", () => {
    const j = tiny();
    j["context_table"][0][0]["start"] = 7;
    expect(pointerOf(j)).toBe("/context_table/0/0/start");
    const k = tiny();
    k["context_table"][1][0]["end"] = -1;
    expect(pointerOf(k)).toBe("/context_table/1/0/end");
    const p = tiny();
    p["context_table"][1][0]["join"]["prefix"] = 5;
    expect(pointerOf(p)).toBe("/context_table/1/0/join/prefix");
  });

  it("rejects malformed patterns", () => {
    const j = tiny();
    j["patterns"][1] = { source: 3 };
    expect(pointerOf(j)).toBe("/patterns/1");
    const k = tiny();
    k["patterns"][1] = { source: "a", flags: "g" };
    expect(pointerOf(k)).toBe("/patterns/1/flags");
  });

  it("rejects wrong top-level shapes", () => {
    for (const key of ["patterns", "context_table", "models", "model_order", "tops"]) {
      const j = tiny();
      j[key] = 5;
      expect(pointerOf(j)).toBe(`/${key}`);
    }
    const j = tiny();
    j["context_table"][1] = "x";
    expect(pointerOf(j)).toBe("/context_table/1");
    const k = tiny();
    k["context_table"][1][0] = null;
    expect(pointerOf(k)).toBe("/context_table/1/0");
    const m = tiny();
    m["models"]["alpha"] = 1;
    expect(pointerOf(m)).toBe("/models/alpha");
    const n = tiny();
    n["models"]["alpha"]["contexts"] = [];
    expect(pointerOf(n)).toBe("/models/alpha/contexts");
  });

  it("requires model_order to list every model exactly once", () => {
    const missing = tiny();
    missing["model_order"] = ["alpha"];
    expect(pointerOf(missing)).toBe("/model_order");
    const dup = tiny();
    dup["model_order"] = ["alpha", "alpha"];
    expect(pointerOf(dup)).toBe("/model_order/1");
    const unknown = tiny();
    unknown["model_order"] = ["alpha", "ghost"];
    expect(pointerOf(unknown)).toBe("/model_order/1");
    const nonString = tiny();
    nonString["model_order"] = ["alpha", 3];
    expect(pointerOf(nonString)).toBe("/model_order/1");
  });

  it("requires tops to name existing models", () => {
    const j = tiny();
    j["tops"]["F"] = "ghost";
    expect(pointerOf(j)).toBe("/tops/F");
  });

  it("carries the message and pointer on the error", () => {
    const err = new EngineFormatError("/x", "bad");
    expect(err.pointer).toBe("/x");
    expect(err.message).toBe("/x: bad");
    expect(err.name).toBe("EngineFormatError");
  });
});
