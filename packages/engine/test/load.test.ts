import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import { Deadline } from "../src/deadline.js";
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

describe("native kinds: split and any", () => {
  // 5 = fast, 6 = sticky head, 7 = sticky tail, 8 = split, 9 = any, 10 = unsupported
  const withSplit = (): Record<string, any> => { // eslint-disable-line
    const j = tiny();
    j["patterns"].push(
      { source: "^a$", flags: "u" },
      { source: "(?<=^(?:a))", flags: "uy" },
      { source: "$", flags: "uy" },
      { split: { head: 6, native: "json-block-body", tail: 7, fast: 5, fast_final: "accept" } },
      { any: [0, 8] },
      { unsupported: "no" },
    );
    return j;
  };
  const SPLIT = "/patterns/8/split";

  it("loads a split and an any and builds cached matchers", () => {
    const m = loadEngine(withSplit());
    expect(m.matcher(8)).toBe(m.matcher(8));
    expect(m.matcher(9).test("a", new Deadline(10_000))).toBe(true);
    expect(m.pattern(6).flags).toBe("uy");
  });

  it("accepts a split without a fast regex", () => {
    const j = withSplit();
    j["patterns"][8]["split"]["fast"] = null;
    expect(loadEngine(j).matcher(8).test("a", new Deadline(10_000))).toBe(true);
  });

  it("rejects an unknown native kind", () => {
    const j = withSplit();
    j["patterns"][8]["split"]["native"] = "json-xml";
    expect(pointerOf(j)).toBe(`${SPLIT}/native`);
    j["patterns"][8]["split"]["native"] = "toString";
    expect(pointerOf(j)).toBe(`${SPLIT}/native`);
    j["patterns"][8]["split"]["native"] = 4;
    expect(pointerOf(j)).toBe(`${SPLIT}/native`);
  });

  it("rejects a bad fast_final", () => {
    const j = withSplit();
    j["patterns"][8]["split"]["fast_final"] = "maybe";
    expect(pointerOf(j)).toBe(`${SPLIT}/fast_final`);
  });

  it("rejects split ids out of range", () => {
    for (const key of ["head", "tail", "fast"]) {
      const j = withSplit();
      j["patterns"][8]["split"][key] = 99;
      expect(pointerOf(j)).toBe(`${SPLIT}/${key}`);
    }
  });

  it("rejects a split that is not an object", () => {
    const j = withSplit();
    j["patterns"][8] = { split: 3 };
    expect(pointerOf(j)).toBe(SPLIT);
  });

  it("requires sticky head and tail and a whole-line fast", () => {
    const head = withSplit();
    head["patterns"][8]["split"]["head"] = 5;
    expect(pointerOf(head)).toBe(`${SPLIT}/head`);
    const tail = withSplit();
    tail["patterns"][8]["split"]["tail"] = 5;
    expect(pointerOf(tail)).toBe(`${SPLIT}/tail`);
    const fast = withSplit();
    fast["patterns"][8]["split"]["fast"] = 6;
    expect(pointerOf(fast)).toBe(`${SPLIT}/fast`);
  });

  it('allows "uy" only for a split head or tail', () => {
    const j = withSplit();
    j["patterns"].push({ source: "^z$", flags: "uy" });
    expect(pointerOf(j)).toBe("/patterns/11/flags");
  });

  it("rejects an any listing an any, a sticky pattern, or a bad id", () => {
    const nested = withSplit();
    nested["patterns"].push({ any: [9] });
    expect(pointerOf(nested)).toBe("/patterns/11/any/0");
    const stickyMember = withSplit();
    stickyMember["patterns"][9]["any"] = [0, 6];
    expect(pointerOf(stickyMember)).toBe("/patterns/9/any/1");
    const range = withSplit();
    range["patterns"][9]["any"] = [99];
    expect(pointerOf(range)).toBe("/patterns/9/any/0");
    const shape = withSplit();
    shape["patterns"][9]["any"] = "x";
    expect(pointerOf(shape)).toBe("/patterns/9/any");
  });

  it("rejects an entry that starts at a sticky sub-pattern", () => {
    const start = withSplit();
    start["context_table"][0][0]["start"] = 6;
    expect(pointerOf(start)).toBe("/context_table/0/0/start");
    const end = withSplit();
    end["context_table"][1][0]["end"] = 7;
    expect(pointerOf(end)).toBe("/context_table/1/0/end");
    const prefix = withSplit();
    prefix["context_table"][1][0]["join"]["prefix"] = 6;
    expect(pointerOf(prefix)).toBe("/context_table/1/0/join/prefix");
  });

  it("accepts entries that reference a split or an any", () => {
    const j = withSplit();
    j["context_table"][0][0]["start"] = 9;
    j["context_table"][1][0]["end"] = 8;
    expect(loadEngine(j).matcher(9)).toBeDefined();
  });

  it("rejects an unsupported pattern with a bad shape and non-string reason", () => {
    const j = withSplit();
    j["patterns"][10] = { unsupported: 3 };
    expect(pointerOf(j)).toBe("/patterns/10/unsupported");
  });

  it("raises ModelError for matcher(unsupported) and pattern(split or any)", () => {
    const m = loadEngine(withSplit());
    expect(() => m.matcher(10)).toThrow(ModelError);
    expect(() => m.pattern(8)).toThrow("pattern 8 is not a plain regex");
    expect(() => m.pattern(9)).toThrow(ModelError);
    expect(() => m.matcher(99)).toThrow(RangeError);
  });
});

describe("guards", () => {
  // 5 = guarded plain, 6 = guarded split (fast 7, head 8, tail 9), 10 = guarded any
  const withGuards = (): Record<string, any> => { // eslint-disable-line
    const j = tiny();
    j["patterns"].push(
      { source: "^json [a-z]+$", flags: "u", guard: "^(?:json )" },
      {
        split: { head: 8, native: "json-block-body", tail: 9, fast: 7, fast_final: "accept" },
        guard: "^(?:data: )",
      },
      { source: "^data: \\[\\];$", flags: "u" },
      { source: "(?<=^(?:data: ))", flags: "uy" },
      { source: ";$", flags: "uy" },
      { any: [5, 6], guard: "^(?:json |data: )" },
    );
    return j;
  };
  const recording = (): { compile: (s: string, f: string) => RegExp; sources: string[] } => {
    const sources: string[] = [];
    return { sources, compile: (s, f) => (sources.push(s), new RegExp(s, f)) };
  };

  it("does not compile a pattern whose guard rejects the line", () => {
    const { compile, sources } = recording();
    const m = loadEngine(withGuards(), { compile });
    expect(m.matcher(5).test("class A", new Deadline(10_000))).toBe(false);
    expect(sources).toEqual(["^(?:json )"]);
  });

  it("compiles and runs the pattern once the guard passes", () => {
    const { compile, sources } = recording();
    const m = loadEngine(withGuards(), { compile });
    expect(m.matcher(5).test("json abc", new Deadline(10_000))).toBe(true);
    expect(m.matcher(5).test("json 123", new Deadline(10_000))).toBe(false);
    expect(sources).toEqual(["^(?:json )", "^json [a-z]+$"]);
  });

  it("guards splits and anys, and leaves pattern(id) unguarded", () => {
    const { compile, sources } = recording();
    const m = loadEngine(withGuards(), { compile });
    expect(m.matcher(10).test("other", new Deadline(10_000))).toBe(false);
    expect(sources).toEqual(["^(?:json |data: )"]);
    expect(m.matcher(6).test("data: [1,[2]];", new Deadline(10_000))).toBe(true);
    expect(m.pattern(5).test("class A")).toBe(false);
  });

  it("rejects a guard that is not a string, or on a sticky or unsupported pattern", () => {
    const j = withGuards();
    j["patterns"][5]["guard"] = 3;
    expect(pointerOf(j)).toBe("/patterns/5/guard");
    const k = withGuards();
    k["patterns"][8]["guard"] = "^(?:a)";
    expect(pointerOf(k)).toBe("/patterns/8/guard");
    const u = withGuards();
    u["patterns"].push({ unsupported: "no", guard: "^(?:a)" });
    expect(pointerOf(u)).toBe("/patterns/11/guard");
  });
});
