// Checks the TS engine against the Python conformance goldens (decision D9, contract C5).
// The one test allowed to read repo files outside the package (decision D6); it skips with
// a message when they are absent, as after the package moves into the monorepo.
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, describe, expect, test } from "vitest";
import {
  ENGINE_FILE,
  FIXTURES_GOLDEN,
  InterpreterCache,
  MAX_TABLE_ROWS,
  ROOT_ENV,
  TOY_DIR,
  TOY_PREFIX,
  blockSplitter,
  blockText,
  compareVerdict,
  formatTable,
  groupByFamily,
  locate,
  parseGoldens,
  readEngine,
  readPythonText,
  repoRoot,
  runGoldens,
  snake,
  toyNames,
} from "./helpers/conformance.js";
import type { Golden, Mismatch } from "./helpers/conformance.js";
import { Interpreter } from "../src/engine.js";
import { entry, toyEngine } from "./helpers/engine.js";

const COLD_START_TIMEOUT_MS = 120_000;
const MIN_FIXTURE_CASES = 3000;
const FIXTURE_PREFIX = "tests/fixtures/";
const DEFAULT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const root = repoRoot();
const located = locate(root);
if (!located.found) console.warn(located.reason);

function expectNoMismatch(mismatches: Mismatch[], total: number): void {
  expect(mismatches.length === 0 ? "" : formatTable(mismatches, total)).toBe("");
}

function registerConformance(base: string): void {
  describe("conformance against the Python goldens", () => {
    const goldens = parseGoldens(readPythonText(join(base, FIXTURES_GOLDEN)));
    const interpreters = new InterpreterCache(readEngine(join(base, ENGINE_FILE)));
    const blocksOf = blockSplitter(base);

    test("fixture goldens are loaded and all name fixture files", () => {
      expect(goldens.length).toBeGreaterThan(MIN_FIXTURE_CASES);
      expect(goldens.every((g) => g.fixture.startsWith(FIXTURE_PREFIX))).toBe(true);
    });

    test.each([...groupByFamily(goldens)])(
      "fixtures: %s",
      (_family, cases) => {
        expectNoMismatch(runGoldens(cases, interpreters, blocksOf), cases.length);
      },
      COLD_START_TIMEOUT_MS,
    );

    test.each(toyNames(base))(
      "toy: %s",
      (name) => {
        const toyRoot = join(base, TOY_DIR);
        const cases = parseGoldens(readPythonText(join(toyRoot, `${name}.jsonl`)));
        const toys = new InterpreterCache(readEngine(join(toyRoot, `${name}.engine.json`)));
        expect(cases.every((c) => c.fixture === `${TOY_PREFIX}${name}`)).toBe(true);
        expectNoMismatch(runGoldens(cases, toys, blocksOf), cases.length);
      },
      COLD_START_TIMEOUT_MS,
    );
  });
}

if (located.found) registerConformance(located.root);
else test.skip(located.reason, () => undefined);

describe("conformance harness", () => {
  const scratch = mkdtempSync(join(tmpdir(), "conformance-"));
  afterAll(() => rmSync(scratch, { recursive: true, force: true }));

  test("an empty root is skipped with a message naming the missing files", () => {
    const result = locate(scratch);
    expect(result.found).toBe(false);
    expect(result.found ? "" : result.reason).toBe(
      `conformance skipped: ${FIXTURES_GOLDEN}, ${ENGINE_FILE}, ${TOY_DIR} not found under ${scratch}`,
    );
  });

  test("the root comes from the environment, else two levels above the package", () => {
    expect(repoRoot({ [ROOT_ENV]: scratch })).toBe(scratch);
    expect(repoRoot({})).toBe(DEFAULT_ROOT);
    expect(repoRoot({ [ROOT_ENV]: "" })).toBe(DEFAULT_ROOT);
  });

  test("a root holding all three inputs is found", () => {
    const full = join(scratch, "full");
    mkdirSync(join(full, TOY_DIR), { recursive: true });
    mkdirSync(join(full, "dist"));
    mkdirSync(join(full, "tests/conformance"), { recursive: true });
    writeFileSync(join(full, FIXTURES_GOLDEN), "");
    writeFileSync(join(full, ENGINE_FILE), "");
    expect(locate(full)).toEqual({ found: true, root: full });
  });

  test("python text is read with universal newlines", () => {
    const file = join(scratch, "crlf.txt");
    writeFileSync(file, "a\r\nb\rc\n");
    expect(readPythonText(file)).toBe("a\nb\nc\n");
  });

  test("an altered golden fails, and the table names the case and field", () => {
    const engine = toyEngine(["anything"], [entry({ start: 0 })]);
    const text = "@startuml\nanything\n@enduml";
    const verdict = new Interpreter(engine).accepts(text, { raw: false });
    const real: Golden = { fixture: "toy/meta", block: 0, raw: false, text, verdict: snake(verdict) };
    const altered: Golden = { ...real, verdict: { ...real.verdict, status: "bogus" } };
    const goldenFile = join(scratch, "meta.jsonl");
    writeFileSync(goldenFile, [real, altered].map((g) => JSON.stringify(g)).join("\n"));
    const cases = parseGoldens(readPythonText(goldenFile));
    const mismatches = runGoldens(cases, new InterpreterCache(engine), () => []);
    expect(mismatches).toEqual([
      { fixture: "toy/meta", block: 0, raw: false, field: "status", python: "bogus", ts: verdict.status },
    ]);
    expect(formatTable(mismatches, cases.length)).toBe(
      [
        "1 mismatching fields in 2 cases",
        "fixture | block | raw | field | python | ts",
        `toy/meta | 0 | false | status | "bogus" | "${verdict.status}"`,
      ].join("\n"),
    );
  });

  test("the table is capped at the row limit but reports the total", () => {
    const many: Mismatch[] = Array.from({ length: MAX_TABLE_ROWS + 5 }, (_v, i) => ({
      fixture: "f",
      block: i,
      raw: true,
      field: "model",
      python: "a",
      ts: "b",
    }));
    const lines = formatTable(many, 9).split("\n");
    expect(lines[0]).toBe(`${MAX_TABLE_ROWS + 5} mismatching fields in 9 cases`);
    expect(lines).toHaveLength(MAX_TABLE_ROWS + 2);
  });

  test("blockText prefers the case text and rejects a missing block", () => {
    const base = { fixture: "x", block: 2, raw: false, verdict: {} as Golden["verdict"] };
    expect(blockText({ ...base, text: "own" }, () => [])).toBe("own");
    expect(blockText(base, () => ["a", "b", "c"])).toBe("c");
    expect(() => blockText(base, () => ["a"])).toThrow("x has no block 2");
  });

  test("compareVerdict reports first_failure under its snake_case name", () => {
    const golden: Golden = {
      fixture: "f",
      block: 0,
      raw: false,
      verdict: { accepted: false, diagram: null, model: null, status: "reject", first_failure: { line: 2, text: "x" } },
    };
    const ts = { accepted: false, diagram: null, model: null, status: "reject" as const, firstFailure: { line: 3, text: "x" } };
    expect(compareVerdict(golden, ts).map((m) => [m.field, m.python, m.ts])).toEqual([
      ["first_failure", { line: 2, text: "x" }, { line: 3, text: "x" }],
    ]);
  });
});
