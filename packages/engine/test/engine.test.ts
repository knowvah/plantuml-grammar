// Ports tests/interp/test_engine.py to the TypeScript interpreter; see helpers/engine-fixtures.ts.
import { describe, expect, it } from "vitest";
import { Interpreter, accepts } from "../src/index.js";
import type { Verdict } from "../src/index.js";
import { failureOf, load, only, uml } from "./helpers/engine-fixtures.js";

const toys = load("toys");

describe("verdicts and dispatch (test_engine.py)", () => {
  it("has exactly the C7 keys", () => {
    expect(accepts(toys, uml("alpha x"))).toEqual({
      accepted: true,
      diagram: "SEQUENCE",
      firstFailure: null,
      model: "seqtoy",
      status: "ok",
    });
  });

  it("accepts a block that only the second diagram matches", () => {
    const v = accepts(toys, uml("beta x", "beta y"));
    expect([v.accepted, v.diagram, v.status]).toEqual([true, "CLASS", "ok"]);
  });

  it("prefers the earlier diagram when both accept", () => {
    expect(accepts(toys, uml("title hello")).model).toBe("seqtoy");
  });

  it("lets start_map order override the default order", () => {
    expect(accepts(toys, uml("title hi"), { startMap: { uml: ["classtoy", "seqtoy"] } }).model).toBe("classtoy");
    expect(accepts(toys, uml("title hi"), { startMap: { "@startuml": ["classtoy"] } }).model).toBe("classtoy");
  });

  it("treats a start_map without the keyword as unsupported, not an error", () => {
    expect(accepts(toys, uml("alpha x"), { startMap: { salt: ["seqtoy"] } })).toEqual({
      accepted: true,
      diagram: null,
      firstFailure: null,
      model: null,
      status: "ok",
    });
  });

  it("rejects at the start line when the keyword maps to no model", () => {
    const v = accepts(toys, uml("alpha x"), { startMap: { uml: ["ghost"] } });
    expect([v.accepted, v.status]).toEqual([false, "reject"]);
    expect(failureOf(v)).toEqual([1, "@startuml"]);
  });

  it("consumes a multiline until its end, then dispatches the next line", () => {
    const v = accepts(toys, uml("note", "anything goes", "alpha ignored by class", "end note", "beta z"));
    expect([v.accepted, v.model]).toEqual([true, "classtoy"]);
  });

  it("can fail on the line after a multiline end", () => {
    const v = accepts(toys, uml("note", "body", "end note", "nonsense here"));
    expect(v.accepted).toBe(false);
    expect(failureOf(v)).toEqual([5, "nonsense here"]);
  });

  it("drops an unterminated multiline and tries the next command", () => {
    const v = accepts(toys, uml("note", "beta x"));
    expect([v.accepted, v.model]).toEqual([true, "classtoy"]);
  });

  it("does not close an outer multiline at an embedded diagram end", () => {
    expect(accepts(toys, uml("note", "{{", "end note", "}}", "end note", "beta q")).accepted).toBe(true);
    const broken = accepts(toys, uml("note", "{{", "end note", "end note", "beta q"));
    expect(failureOf(broken)).toEqual([3, "{{"]);
  });

  it("reports the 1-based line and raw text of the failure", () => {
    const v = accepts(toys, "\n@startuml\nalpha ok\n  bogus line  \n@enduml");
    expect(v).toEqual({
      accepted: false,
      diagram: null,
      firstFailure: { line: 4, text: "  bogus line  " },
      model: null,
      status: "reject",
    });
  });

  it("lets the earlier of two matching commands win by its push", () => {
    expect(accepts(toys, uml("dup", "one")).accepted).toBe(true);
    expect(failureOf(accepts(toys, uml("dup", "two")))).toEqual([3, "two"]);
  });

  it("pops back to main and pushes into a body", () => {
    expect(accepts(toys, uml("open {", "member a", "member b", "}", "beta c")).accepted).toBe(true);
    expect(failureOf(accepts(toys, uml("member a")))).toEqual([2, "member a"]);
    expect(failureOf(accepts(toys, uml("open {", "beta c")))).toEqual([3, "beta c"]);
  });

  it("replaces the top of the stack on set", () => {
    expect(accepts(toys, uml("swap", "two")).accepted).toBe(true);
    expect(failureOf(accepts(toys, uml("swap", "one")))).toEqual([3, "one"]);
    expect(failureOf(accepts(toys, uml("swap", "two", "beta x")))).toEqual([4, "beta x"]);
  });

  it("treats pop on the bottom context as a no-op", () => {
    expect(failureOf(accepts(toys, uml("}")))).toEqual([2, "}"]);
  });

  it("balances nested braces in a bracket command", () => {
    expect(accepts(toys, uml("package a {", "inner {", "}", "}", "beta x")).accepted).toBe(true);
    const unbalanced = accepts(toys, uml("package a {", "inner {", "}", "beta x"));
    expect([unbalanced.accepted, ...failureOf(unbalanced)]).toEqual([false, 2, "package a {"]);
  });

  it("drops a bracket command whose depth goes negative", () => {
    expect(failureOf(accepts(toys, uml("package a {", "}", "}")))).toEqual([4, "}"]);
  });

  it("swallows the rest of the block in an opaque command", () => {
    const text = "@startdot\ndigraph g {\n a -> b ; ((( not parsed\n}\n@enddot";
    const v = accepts(toys, text);
    expect([v.accepted, v.model]).toEqual([true, "dottoy"]);
    expect(failureOf(accepts(toys, "@startdot\nnot digraph\n@enddot"))).toEqual([2, "not digraph"]);
  });

  it("ignores comments, blank lines and text after the end line", () => {
    const text = [
      "@startuml", "' a line comment", "", "/' one liner '/", "/' multi",
      "this is not a command", "'/", "alpha x", "@enduml", "garbage after end",
    ].join("\n");
    expect(accepts(toys, text).accepted).toBe(true);
  });

  it("rejects an empty body at the start line", () => {
    const v = accepts(toys, "\n@startuml\n' only a comment\n\n@enduml");
    expect([v.accepted, v.status]).toEqual([false, "reject"]);
    expect(failureOf(v)).toEqual([2, "@startuml"]);
  });

  it("tries every diagram model for a bare body", () => {
    expect(accepts(toys, "beta x").model).toBe("classtoy");
    expect(failureOf(accepts(toys, "alpha x\nzzz"))).toEqual([2, "zzz"]);
  });

  it("accepts an unknown start keyword as unsupported", () => {
    const v = accepts(toys, "@startnope\nalpha x\n@endnope");
    expect([v.accepted, v.status, v.diagram]).toEqual([true, "ok", null]);
  });

  it("reports the failure that got furthest, first candidate winning ties", () => {
    expect(failureOf(accepts(toys, uml("alpha x", "beta y")))).toEqual([3, "beta y"]);
    expect(failureOf(accepts(toys, uml("beta x", "beta y", "alpha z")))).toEqual([4, "alpha z"]);
  });

  it("trims CRLF and indentation", () => {
    expect(accepts(toys, "@startuml\r\n\talpha x  \r\n@enduml\r\n").accepted).toBe(true);
  });

  it("uses the default 10 s budget when none is given", () => {
    let now = 0;
    const clock = (): number => now;
    const interp = new Interpreter(toys, { clock });
    expect(interp.accepts(uml("alpha x")).accepted).toBe(true);
    now = 9_999;
    expect(interp.accepts(uml("alpha x")).status).toBe("ok");
  });
});

describe("timeouts and model errors", () => {
  const single = load("single");
  const TIMEOUT_VERDICT: Verdict = {
    accepted: false,
    diagram: null,
    firstFailure: null,
    model: null,
    status: "timeout",
  };

  it("gives timeout when the budget is spent before the first regex call", () => {
    const ticks = [0, 5_000];
    let n = 0;
    const clock = (): number => ticks[Math.min(n++, ticks.length - 1)] ?? 0;
    const v = new Interpreter(single, { ...only("s-x"), clock }).accepts(uml("x"), { timeoutMs: 1_000 });
    expect(v).toEqual(TIMEOUT_VERDICT);
  });

  it("gives timeout when a fake clock expires mid-block", () => {
    let now = 0;
    const clock = (): number => (now += 1);
    const v = new Interpreter(toys, { clock }).accepts(uml("alpha a", "alpha b", "alpha c", "alpha d"), {
      timeoutMs: 3,
    });
    expect(v).toEqual(TIMEOUT_VERDICT);
  });

  it("gives timeout during the raw-mode preproc filter", () => {
    let now = 0;
    const clock = (): number => (now += 1);
    const v = new Interpreter(toys, { clock }).accepts(uml("!define X 1", "!define Y 2", "alpha x"), {
      raw: true,
      timeoutMs: 3,
    });
    expect(v).toEqual(TIMEOUT_VERDICT);
  });

  const ERROR_VERDICT: Verdict = { ...TIMEOUT_VERDICT, status: "error" };

  it("gives error for an uncompilable model regex", () => {
    expect(accepts(single, uml("x"), only("s-paren"))).toEqual(ERROR_VERDICT);
  });

  it("gives error for an unsupported pattern", () => {
    expect(accepts(single, uml("x"), only("s-set"))).toEqual(ERROR_VERDICT);
  });

  it("gives error for an unresolved part", () => {
    expect(accepts(single, uml("x"), only("s-ref"))).toEqual(ERROR_VERDICT);
  });

  it("gives error for a push to a missing context", () => {
    expect(accepts(single, uml("x", "y"), only("s-ghost"))).toEqual(ERROR_VERDICT);
  });

  it("gives error when a regex overflows the stack", () => {
    const engine = load("single");
    Object.defineProperty(engine, "context", {
      value: () => {
        throw new RangeError("Maximum call stack size exceeded");
      },
    });
    expect(accepts(engine, uml("x"), only("s-x"))).toEqual(ERROR_VERDICT);
  });

  it("rethrows an unexpected exception", () => {
    const engine = load("single");
    Object.defineProperty(engine, "context", { value: () => { throw new TypeError("boom"); } });
    expect(() => accepts(engine, uml("x"), only("s-x"))).toThrow("boom");
  });

  it("keeps Java line separators for the regex", () => {
    const opts = only("s-title");
    expect(accepts(single, uml("title a "), opts).accepted).toBe(true);
    expect(accepts(single, uml("title a\x85"), opts).accepted).toBe(true);
    const rejected = accepts(single, uml("title a b"), opts);
    expect([rejected.accepted, ...failureOf(rejected)]).toEqual([false, 2, "title a b"]);
    expect(accepts(single, uml("title a  "), opts).accepted).toBe(false);
    expect(accepts(single, uml("title –"), opts).accepted).toBe(true);
  });
});

describe("accepts cache", () => {
  it("follows engine identity", () => {
    const other = load("single");
    expect(accepts(toys, uml("alpha x")).model).toBe("seqtoy");
    expect(accepts(other, uml("x"), only("s-only")).model).toBe("s-only");
    expect(accepts(toys, uml("alpha x")).model).toBe("seqtoy");
  });

  it("follows startMap identity", () => {
    const first = { uml: ["classtoy"] };
    const second = { uml: ["seqtoy"] };
    expect(accepts(toys, uml("title t"), { startMap: first }).model).toBe("classtoy");
    expect(accepts(toys, uml("title t"), { startMap: first }).model).toBe("classtoy");
    expect(accepts(toys, uml("title t"), { startMap: second }).model).toBe("seqtoy");
  });
});

describe("join (test_engine.py)", () => {
  it("treats k = 1 as the single-line case", () => {
    expect(accepts(toys, uml("opt", "beta x")).accepted).toBe(true);
  });

  it("takes the smallest k", () => {
    expect(failureOf(accepts(toys, uml("opt", "z")))).toEqual([3, "z"]);
  });

  it("joins following lines with the private-use joiner", () => {
    expect(accepts(toys, uml("wrap a", "b", "beta x")).accepted).toBe(true);
    expect(failureOf(accepts(toys, uml("wrap a", "b", "c")))).toEqual([4, "c"]);
  });

  it("drops a join beyond max_lines + 1 units", () => {
    expect(failureOf(accepts(toys, uml("far", "a", "b", "c")))).toEqual([2, "far"]);
  });

  it("drops a join when lines run out", () => {
    expect(failureOf(accepts(toys, uml("wrap a")))).toEqual([2, "wrap a"]);
  });

  it("treats an embedded group as one unit", () => {
    expect(failureOf(accepts(toys, uml("wrap a", "{{uml", "x", "}}")))).toEqual([2, "wrap a"]);
  });
});

