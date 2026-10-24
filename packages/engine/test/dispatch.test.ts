import { describe, expect, it } from "vitest";
import {
  Dispatcher,
  FACTORY_TYPE_ORDER,
  START_TYPES,
  UML_TYPES,
  documentStartMap,
  lookup,
  startTypes,
  type ModelRef,
} from "../src/dispatch.js";
import type { EngineModelJson } from "../src/types.js";

function model(
  diagram: string | null,
  extra: Partial<EngineModelJson> = {},
): EngineModelJson {
  return {
    layer: "diagram",
    diagram,
    factory: null,
    glue_units: false,
    empty_needs_end: false,
    start_map: {},
    includes: [],
    contexts: {},
    ...extra,
  };
}

const ids = (found: ModelRef[] | null): string[] | null =>
  found === null ? null : found.map((r) => r.id);

function build(entries: [string, EngineModelJson][]): {
  models: Record<string, EngineModelJson>;
  order: string[];
} {
  return { models: Object.fromEntries(entries), order: entries.map(([id]) => id) };
}

function plain(): ReturnType<typeof build> {
  return build([
    ["state", model("STATE")],
    ["seq", model("SEQUENCE")],
    ["mind", model("MINDMAP")],
    ["shared", model(null, { layer: "shared" })],
    ["cls", model("CLASS")],
  ]);
}

describe("startTypes", () => {
  it("mirrors findStartTypes", () => {
    expect(startTypes("uml")).toBe(UML_TYPES);
    expect(startTypes("umlfoo")).toBe(UML_TYPES);
    expect([...startTypes("project")]).toEqual(["GANTT"]);
    expect([...startTypes("mindmap")]).toEqual(["MINDMAP"]);
    expect(startTypes("zzz").size).toBe(0);
  });

  it("keeps the table sizes", () => {
    expect(START_TYPES.size).toBe(31);
    expect(FACTORY_TYPE_ORDER.slice(0, 3)).toEqual(["SEQUENCE", "CLASS", "ACTIVITY"]);
  });
});

describe("Dispatcher without a start map", () => {
  it("filters by type and sorts by factory order", () => {
    const { models, order } = plain();
    const d = new Dispatcher(models, order, {});
    expect(ids(d.plan("uml"))).toEqual(["seq", "cls", "state"]);
    expect(ids(d.plan("mindmap"))).toEqual(["mind"]);
    expect(ids(d.plan(null))).toEqual(["state", "seq", "mind", "cls"]);
    expect(d.plan("zzz")).toBeNull();
  });

  it("uses model_order, not integer-like key order", () => {
    const { models, order } = build([
      ["b", model("SEQUENCE")],
      ["1", model("SEQUENCE")],
    ]);
    expect(ids(new Dispatcher(models, order, {}).plan(null))).toEqual(["b", "1"]);
  });

  it("ranks models with no known diagram type last", () => {
    const { models, order } = build([
      ["x", model("CRASH")],
      ["y", model("SEQUENCE")],
    ]);
    expect(ids(new Dispatcher(models, order, {}, undefined).plan("uml"))).toEqual(["y"]);
  });
});

describe("lookup", () => {
  const table = { uml: ["A"], "@startdot": ["B"], def: ["C"] };
  it("is exact, then @start-prefixed, then prefix", () => {
    expect(lookup(table, "uml")).toEqual(["A"]);
    expect(lookup(table, "dot")).toEqual(["B"]);
    expect(lookup(table, "umlfoo")).toEqual(["A"]);
    expect(lookup(table, "definition")).toEqual(["C"]);
    expect(lookup(table, "zzz")).toBeNull();
    expect(lookup(table, "")).toBeNull();
  });

  it("ignores inherited object properties", () => {
    expect(lookup({}, "constructor")).toBeNull();
  });
});

function family(): { models: Record<string, EngineModelJson>; order: string[]; tops: Record<string, string> } {
  const { models, order } = build([
    ["doc", model(null, {
      layer: "document",
      start_map: { uml: ["SeqF", "ClassF", "ActF", "ActF3"], mindmap: ["MindF"] },
    })],
    ["seq", model("SEQUENCE", { factory: "SeqF" })],
    ["cls", model("CLASS", { factory: "ClassF" })],
    ["clsfamily", model("CLASS", { factory: "ClassF", includes: ["cls"] })],
    ["act", model("ACTIVITY", { factory: "ActF" })],
    ["act3", model("ACTIVITY", { factory: "ActF3" })],
    ["mind", model("MINDMAP", { factory: "MindF" })],
  ]);
  const tops = { SeqF: "seq", ClassF: "clsfamily", ActF: "act", ActF3: "act3", MindF: "mind" };
  return { models, order, tops };
}

describe("Dispatcher with the document start map", () => {
  it("picks the top model per factory in map order", () => {
    const { models, order, tops } = family();
    const d = new Dispatcher(models, order, tops);
    expect(ids(d.plan("uml"))).toEqual(["seq", "clsfamily", "act", "act3"]);
    expect(ids(d.plan("umlish"))).toEqual(["seq", "clsfamily", "act", "act3"]);
    expect(ids(d.plan("mindmap"))).toEqual(["mind"]);
    expect(d.plan("zzz")).toBeNull();
  });

  it("accepts factories and diagram model ids in an explicit map", () => {
    const { models, order, tops } = family();
    const d = new Dispatcher(models, order, tops, { uml: ["ClassF", "seq", "ghost"] });
    expect(ids(d.plan("uml"))).toEqual(["clsfamily", "seq"]);
    const doc = new Dispatcher(models, order, tops, { uml: ["doc"] });
    expect(ids(doc.plan("uml"))).toEqual([]);
  });

  it("falls back to diagram types without a document model", () => {
    const { models, order, tops } = family();
    const { doc: _doc, ...rest } = models;
    const d = new Dispatcher(rest, order.filter((i) => i !== "doc"), tops);
    expect(ids(d.plan("mindmap"))).toEqual(["mind"]);
  });

  it("skips top ids missing from the model set", () => {
    const { models, order } = family();
    const d = new Dispatcher(models, order, { MindF: "gone" });
    expect(ids(d.plan("mindmap"))).toEqual([]);
  });
});

describe("documentStartMap", () => {
  it("takes the first non-empty document map and ignores empty ones", () => {
    const { models, order } = build([
      ["d0", model(null, { layer: "document" })],
      ["d1", model(null, { layer: "document", start_map: { a: ["X"] } })],
      ["d2", model(null, { layer: "document", start_map: { b: ["Y"] } })],
    ]);
    expect(documentStartMap(models, order)).toEqual({ a: ["X"] });
    expect(documentStartMap(models, ["d0", "missing"])).toBeNull();
  });
});
