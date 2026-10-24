import { describe, expect, it } from "vitest";
import { Deadline } from "../src/deadline.js";
import { UnknownContextError } from "../src/load.js";
import { ACTION_PUSH, buildRule, RuleBook } from "../src/rules.js";
import { entry, lines, MAIN, MODEL_ID, STYLE_PREFIX, STYLE_START, toyEngine } from "./helpers/engine.js";

const BUDGET_MS = 10_000;
const fresh = (): Deadline => new Deadline(BUDGET_MS);

function ruleOf(sources: string[], e: ReturnType<typeof entry>, glue = true) {
  const engine = toyEngine(sources, [e], glue);
  const model = engine.models.get(MODEL_ID);
  if (model === undefined) throw new Error("model missing");
  return buildRule(e, model, engine);
}

describe("Rule.advance", () => {
  it("single advances one line on a match, null otherwise", () => {
    const rule = ruleOf(["a"], entry({ start: 0 }));
    expect(rule.advance(lines("a", "b"), 0, fresh())).toBe(1);
    expect(rule.advance(lines("b"), 0, fresh())).toBeNull();
    expect(rule.advance(lines(), 0, fresh())).toBeNull();
  });
  it("opaque consumes the rest of the body", () => {
    const rule = ruleOf(["a"], entry({ start: 0, kind: "opaque" }));
    expect(rule.advance(lines("a", "x", "y"), 0, fresh())).toBe(3);
  });
  it("multiline finds the end line", () => {
    const rule = ruleOf(["s", "e"], entry({ start: 0, end: 1, kind: "multiline" }));
    expect(rule.advance(lines("s", "x", "e", "z"), 0, fresh())).toBe(3);
    expect(rule.advance(lines("s", "x"), 0, fresh())).toBeNull();
  });
  it("multiline without an end pattern drops the command", () => {
    const rule = ruleOf(["s"], entry({ start: 0, kind: "multiline" }));
    expect(rule.advance(lines("s", "x"), 0, fresh())).toBeNull();
  });
  it("multiline glues {{ }} only when glue_units is true", () => {
    const e = entry({ start: 0, end: 1, kind: "multiline" });
    const body = lines("s", "{{", "e", "}}", "e");
    expect(ruleOf(["s", "e"], e, true).advance(body, 0, fresh())).toBe(5);
    expect(ruleOf(["s", "e"], e, false).advance(body, 0, fresh())).toBe(3);
  });
  it("bracket tracks depth and returns null below zero", () => {
    const rule = ruleOf(["a \\{"], entry({ start: 0, kind: "multiline-bracket" }));
    expect(rule.advance(lines("a {", "x", "}"), 0, fresh())).toBe(3);
    expect(rule.advance(lines("a {", "{{", "}", "}", "}}"), 0, fresh())).toBeNull();
  });
  it("join uses the prefix pattern", () => {
    const rule = ruleOf(
      [STYLE_START, STYLE_PREFIX],
      entry({ start: 0, kind: "multiline", join: { max_lines: 10, prefix: 1 } }),
    );
    expect(rule.advance(lines("<style>", "a", "</style>"), 0, fresh())).toBe(3);
    expect(rule.advance(lines("class A", "a"), 0, fresh())).toBeNull();
  });
  it("untrimmed matches Line.text, trimmed rules match Line.trimmed", () => {
    const body = lines("  ++ x  ");
    const raw = ruleOf(["\\+\\+ \\w+"], entry({ start: 0, untrimmed: true }));
    const trimmed = ruleOf(["\\+\\+ \\w+"], entry({ start: 0 }));
    expect(raw.advance(body, 0, fresh())).toBeNull();
    expect(raw.advance(lines("++ x"), 0, fresh())).toBe(1);
    expect(trimmed.advance(body, 0, fresh())).toBe(1);
  });
});

describe("buildRule", () => {
  it("copies transition fields from the entry", () => {
    const rule = ruleOf(
      ["a"],
      entry({ start: 0, command: "Go", action: "push", target: "inner", gives: "g", needs: "n", reject: true, require_pop: true }),
    );
    expect(rule).toMatchObject({
      name: "Go", action: ACTION_PUSH, target: "inner", gives: "g", needs: "n",
      reject: true, requirePop: true, untrimmed: false, glueUnits: true, join: null, end: null,
    });
  });
  it("builds a join without prefix as non-stopping", () => {
    const e = entry({ start: 0, join: { max_lines: 3, prefix: 0 } });
    const engine = toyEngine(["a"], [e]);
    const model = engine.models.get(MODEL_ID);
    if (model === undefined) throw new Error("model missing");
    const { max_lines } = e.join ?? { max_lines: 0 };
    const rule = buildRule({ ...e, join: { max_lines } as never }, model, engine);
    expect(rule.join?.prefix).toBeNull();
    expect(rule.join?.maxLines).toBe(3);
  });
});

describe("RuleBook", () => {
  it("caches rules per context", () => {
    const engine = toyEngine(["a"], [entry({ start: 0 })]);
    const book = new RuleBook(engine);
    const first = book.rules(MODEL_ID, MAIN);
    expect(first.map((r) => r.name)).toEqual(["Cmd"]);
    expect(book.rules(MODEL_ID, MAIN)).toBe(first);
  });
  it("throws UnknownContextError for a missing context or model", () => {
    const book = new RuleBook(toyEngine(["a"], [entry({ start: 0 })]));
    expect(() => book.rules(MODEL_ID, "nope")).toThrow(UnknownContextError);
    expect(() => book.rules("zzz", MAIN)).toThrow(UnknownContextError);
  });
});
