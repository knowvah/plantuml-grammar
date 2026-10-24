// Ports tests/interp/test_document_dispatch.py and test_plain_lines_empty_end.py to the TypeScript interpreter; see helpers/engine-fixtures.ts.
import { describe, expect, it } from "vitest";
import { accepts } from "../src/index.js";
import { END_LINE, failureOf, load, only, uml } from "./helpers/engine-fixtures.js";

describe("document dispatch (test_document_dispatch.py)", () => {
  const family = load("dispatch");

  it("reports the diagram type and top model id", () => {
    const cls = accepts(family, uml("cls x"));
    expect([cls.diagram, cls.model]).toEqual(["CLASS", "clsfamily"]);
    const act3 = accepts(family, uml("act3 y"));
    expect([act3.diagram, act3.model]).toEqual(["ACTIVITY", "act3"]);
  });

  it("tries the document start_map factories in map order", () => {
    expect(accepts(family, uml("seq a")).model).toBe("seq");
    expect(accepts(family, uml("act b")).model).toBe("act");
  });

  it("accepts an unknown keyword as unsupported with a document map", () => {
    const v = accepts(family, "@startfoo\nseq\n@endfoo");
    expect([v.accepted, v.diagram, v.model]).toEqual([true, null, null]);
  });

  describe("empty bodies", () => {
    const empty = load("empty");

    it("lets an empty context accept an empty body", () => {
      expect(accepts(empty, uml(), only("e1")).model).toBe("e1");
      expect(accepts(empty, uml("", "' comment"), only("e1")).accepted).toBe(true);
      expect(failureOf(accepts(empty, uml("x"), only("e1")))).toEqual([2, "x"]);
    });

    it("shows the empty context blank lines and then the end line", () => {
      expect(accepts(empty, uml(), only("e2")).accepted).toBe(true);
      expect(failureOf(accepts(empty, uml(""), only("e2")))).toEqual([3, END_LINE]);
      expect(accepts(empty, "", only("e2")).accepted).toBe(true);
    });

    it("rejects an empty body at the start line without an empty context", () => {
      expect(failureOf(accepts(empty, uml(), only("e3")))).toEqual([1, "@startuml"]);
    });
  });
});

describe("plain-line factories and empty_needs_end (test_plain_lines_empty_end.py)", () => {
  const plain = load("plain-lines");
  const GLUED = ["<style>", "{{", "a", "</style>", "tail"];

  it("glues an embedded unit in a command factory so the join cannot stop", () => {
    const v = accepts(plain, uml(...GLUED), only("style-cmd"));
    expect([v.accepted, ...failureOf(v)]).toEqual([false, 2, "<style>"]);
  });

  it("joins across a brace line in a plain-line factory", () => {
    const v = accepts(plain, uml(...GLUED), only("style-plain"));
    expect([v.accepted, v.model]).toEqual([true, "style-plain"]);
  });

  it("still rejects an unclosed region in a plain-line factory", () => {
    const v = accepts(plain, uml("<style>", "{{", "a"), only("style-plain"));
    expect([v.accepted, ...failureOf(v)]).toEqual([false, 2, "<style>"]);
  });

  it("accepts a truncated empty block without the key", () => {
    expect(accepts(plain, "@startuml", only("welcome")).accepted).toBe(true);
    expect(accepts(plain, "@startuml\n@enduml", only("welcome")).accepted).toBe(true);
  });

  it("refuses a truncated empty block with the key", () => {
    const v = accepts(plain, "@startuml", only("welcome-strict"));
    expect([v.accepted, ...failureOf(v)]).toEqual([false, 1, "@startuml"]);
    expect(accepts(plain, "@startuml\n@enduml", only("welcome-strict")).accepted).toBe(true);
  });

  it("keeps a bare body without start or end accepted", () => {
    expect(accepts(plain, "", only("welcome-strict")).accepted).toBe(true);
  });
});
