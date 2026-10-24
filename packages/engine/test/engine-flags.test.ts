// Ports tests/interp/test_flags_trim.py to the TypeScript interpreter; see helpers/engine-fixtures.ts.
import { describe, expect, it } from "vitest";
import { accepts } from "../src/index.js";
import { END_LINE, failureOf, load, only, runner, uml } from "./helpers/engine-fixtures.js";

describe("gives / needs and untrimmed rules (test_flags_trim.py)", () => {
  const run = runner(load("flags"));

  it("fails an unmet need at the end line", () => {
    expect(run("fl-sep-task", "-- a --")).toEqual([false, [3, END_LINE]]);
  });

  it("is satisfied by a give after or before the need", () => {
    expect(run("fl-sep-task", "-- a --", "task x")).toEqual([true, null]);
    expect(run("fl-sep-task", "task x", "-- a --")).toEqual([true, null]);
  });

  it("does nothing when nothing needs the flag", () => {
    expect(run("fl-sep-task", "task x")).toEqual([true, null]);
  });

  it("satisfies several needs with one give", () => {
    expect(run("fl-sep-task", "-- a --", "-- b --", "task x")).toEqual([true, null]);
  });

  it("is not satisfied by a give of another flag", () => {
    expect(run("fl-other", "-- a --", "other")).toEqual([false, [4, END_LINE]]);
  });

  it("reports syntax errors before the final-state check", () => {
    expect(run("fl-sep-task", "-- a --", "nope")).toEqual([false, [3, "nope"]]);
  });

  it("counts a flag given inside a pushed context after the pop", () => {
    expect(run("fl-group", "-- a --", "grp {", "task x", "}")).toEqual([true, null]);
  });

  it("fails a group with no task inside at the end line", () => {
    expect(run("fl-group", "grp {", "}")).toEqual([false, [4, END_LINE]]);
  });

  it("discards a give made inside an abandoned body", () => {
    expect(run("fl-open", "-- a --", "open {", "task x")).toEqual([false, [5, END_LINE]]);
  });

  it("keeps gives made before the push on backtrack", () => {
    expect(run("fl-open-task", "-- a --", "task x", "open {", "task y")).toEqual([true, null]);
  });

  it("discards a need made inside an abandoned body", () => {
    expect(run("fl-open-nosep", "open {", "-- a --")).toEqual([true, null]);
  });

  it("keeps the give of a closed body", () => {
    expect(run("fl-open", "-- a --", "open {", "task x", "}")).toEqual([true, null]);
  });

  it("fails a reject entry with flags at its line", () => {
    expect(run("fl-bad", "-- a --", "bad")).toEqual([false, [3, "bad"]]);
  });

  it("reports the last line when there is no end directive", () => {
    const v = accepts(load("flags"), "@startuml\n-- a --", only("fl-sep-task"));
    expect([v.accepted, ...failureOf(v)]).toEqual([false, 2, "-- a --"]);
  });

  it("ignores preproc entries' flags in raw mode", () => {
    const engine = load("flags");
    const raw = accepts(engine, uml("!task", "-- a --"), { ...only("fl-sep-task"), raw: true });
    expect([raw.accepted, ...failureOf(raw)]).toEqual([false, 4, END_LINE]);
    expect(accepts(engine, uml("!sep", "task x"), { ...only("fl-sep-task"), raw: true }).accepted).toBe(true);
  });

});

describe("untrimmed rules (test_flags_trim.py)", () => {
  const run = runner(load("flags"));

  it.each([
    ["++ b", true],
    ["  ++ b", false],
    ["\t++ b", false],
    ["++ b ", false],
    ["++ b\t", false],
    [" ++ b", false],
  ] as const)("matches an untrimmed rule against the raw line %j", (line, ok) => {
    expect(run("fl-plus", line)[0]).toBe(ok);
  });

  it("reports the raw text of an untrimmed failure", () => {
    expect(run("fl-plus", "  ++ b")).toEqual([false, [2, "  ++ b"]]);
  });

  it("still matches default rules against the trimmed line", () => {
    expect(run("fl-plus-dash", "  -- b  ", "\t-- c")).toEqual([true, null]);
  });

  it("drops the trailing carriage return", () => {
    const v = accepts(load("flags"), "@startuml\r\n++ b\r\n@enduml\r\n", only("fl-plus"));
    expect(v.accepted).toBe(true);
  });

  it("skips an untrimmed rule so a later rule can take the line", () => {
    expect(run("fl-plus-any", "  ++ b")).toEqual([true, null]);
  });

  it("applies trim from override patches", () => {
    expect(run("fl-dash-ovr", "-- b")).toEqual([true, null]);
    expect(run("fl-dash-ovr", " -- b")).toEqual([false, [2, " -- b"]]);
  });
});

