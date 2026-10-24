// Tests for src/cli.ts: argument parsing, job parsing, ordered JSONL streaming (contract C6).
import { spawnSync } from "node:child_process";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { accepts } from "../src/index.js";
import { EXIT_FAILURE, EXIT_OK, EXIT_USAGE, main, parseCliArgs, parseJobLine } from "../src/cli.js";
import { toWire, timeoutVerdict } from "../src/pool.js";
import { loadFromPath } from "../src/worker.js";
import { uml } from "./helpers/engine-fixtures.js";
import { HOOKS, ENGINE_FIXTURE, TEST_TIMEOUT_MS, buildEngine, linesOf } from "./helpers/pool-env.js";
import type { Built } from "./helpers/pool-env.js";

const { engine } = loadFromPath(ENGINE_FIXTURE);
const OK_TEXT = uml("alpha x");
const REJECT_TEXT = uml("zzz");
const BETA_TEXT = uml("beta x", "beta y");
const expected = (text: string) => toWire(accepts(engine, text));
const jobLine = (id: string, text: string, extra: object = {}) => JSON.stringify({ id, text, ...extra });

let built: Built;
beforeAll(() => {
  built = buildEngine();
}, TEST_TIMEOUT_MS);
afterAll(() => built.cleanup());

async function runMain(argv: string[], lines: string[], extra: { hook?: string; grace?: number } = {}) {
  const out: string[] = [];
  const err: string[] = [];
  const code = await main(argv, {
    lines: linesOf(lines),
    stdout: (s) => out.push(s),
    stderr: (s) => err.push(s),
    poolOptions: {
      workerUrl: built.workerUrl,
      ...(extra.hook === undefined ? {} : { hookModule: extra.hook }),
      ...(extra.grace === undefined ? {} : { killGraceMs: extra.grace }),
    },
  });
  const parse = (chunks: string[]) => chunks.join("").split("\n").filter(Boolean).map((l) => JSON.parse(l));
  return { code, results: parse(out), logs: parse(err) };
}

describe("parseCliArgs", () => {
  it("requires --engine and defaults workers", () => {
    expect(parseCliArgs(["--engine", "e.json"], 6)).toEqual({ ok: true, value: { engine: "e.json", workers: 6 } });
    expect(parseCliArgs([], 6)).toEqual({ ok: false, message: "usage: --engine <path> is required" });
  });

  it("parses --workers and rejects bad values and unknown flags", () => {
    expect(parseCliArgs(["--engine", "e", "--workers", "3"], 6)).toEqual({
      ok: true,
      value: { engine: "e", workers: 3 },
    });
    for (const bad of ["0", "-1", "x", "1.5"]) {
      expect(parseCliArgs(["--engine", "e", `--workers=${bad}`], 6)).toEqual({
        ok: false,
        message: "usage: --workers must be a positive integer",
      });
    }
    const unknown = parseCliArgs(["--engine", "e", "--nope"], 6);
    expect(unknown.ok).toBe(false);
    expect(unknown.ok ? "" : unknown.message).toMatch(/^usage: --engine <path> \[--workers N\]/);
  });
});

describe("parseJobLine", () => {
  it("applies defaults for raw and timeout_s", () => {
    expect(parseJobLine(jobLine("a", "t"))).toEqual({
      ok: true,
      value: { id: "a", text: "t", raw: false, timeout_s: 10 },
    });
    expect(parseJobLine(jobLine("a", "t", { raw: true, timeout_s: 2.5 }))).toEqual({
      ok: true,
      value: { id: "a", text: "t", raw: true, timeout_s: 2.5 },
    });
  });

  it.each([
    ["{not json", "not valid JSON"],
    ["[1]", "job must be a JSON object"],
    ["null", "job must be a JSON object"],
    ['{"text":"t"}', "id must be a string"],
    ['{"id":"a"}', "text must be a string"],
    ['{"id":"a","text":"t","raw":1}', "raw must be a boolean"],
    ['{"id":"a","text":"t","timeout_s":0}', "timeout_s must be a positive number"],
    ['{"id":"a","text":"t","timeout_s":"5"}', "timeout_s must be a positive number"],
  ])("rejects %s", (line, message) => {
    expect(parseJobLine(line)).toEqual({ ok: false, message });
  });
});

describe("main", () => {
  it("emits results in input order with verdicts equal to accepts, and logs start/end", async () => {
    const texts = [OK_TEXT, REJECT_TEXT, BETA_TEXT];
    const lines = ["", ...texts.map((t, i) => jobLine(`id${i}`, t))];
    const { code, results, logs } = await runMain(["--engine", ENGINE_FIXTURE, "--workers", "2"], lines);
    expect(code).toBe(EXIT_OK);
    expect(results).toEqual(texts.map((t, i) => ({ id: `id${i}`, verdict: expected(t) })));
    const start = logs.find((l) => l.msg === "start");
    expect(start).toMatchObject({ level: "info", service: "plantuml-engine", engine: ENGINE_FIXTURE, workers: 2 });
    expect(start.patterns).toBeGreaterThan(0);
    expect(logs.find((l) => l.msg === "end")).toMatchObject({ jobs: 3, statuses: { ok: 2, reject: 1 } });
    expect(JSON.stringify(logs)).not.toContain("alpha");
  }, TEST_TIMEOUT_MS);

  it("keeps order when a timeout is mixed in, and warns", async () => {
    const lines = [jobLine("a", OK_TEXT), jobLine("slow", "spin", { timeout_s: 0.2 }), jobLine("b", REJECT_TEXT)];
    const { code, results, logs } = await runMain(["--engine", ENGINE_FIXTURE, "--workers", "1"], lines, {
      hook: HOOKS,
      grace: 100,
    });
    expect(code).toBe(EXIT_OK);
    expect(results).toEqual([
      { id: "a", verdict: expected(OK_TEXT) },
      { id: "slow", verdict: timeoutVerdict() },
      { id: "b", verdict: expected(REJECT_TEXT) },
    ]);
    expect(logs.filter((l) => l.level === "warn")).toHaveLength(1);
    expect(logs.find((l) => l.msg === "end").statuses).toEqual({ ok: 1, timeout: 1, reject: 1 });
  }, TEST_TIMEOUT_MS);

  it("gives a throwing job status error with line 0 and exit 0", async () => {
    const { code, results } = await runMain(["--engine", ENGINE_FIXTURE, "--workers", "1"], [jobLine("t", "throw")], {
      hook: HOOKS,
    });
    expect(code).toBe(EXIT_OK);
    expect(results[0].verdict).toMatchObject({ status: "error", first_failure: { line: 0, text: "boom" } });
  }, TEST_TIMEOUT_MS);

  it("exits 2 with an error log on a malformed line, after flushing earlier results", async () => {
    const lines = [jobLine("a", OK_TEXT), "{oops", jobLine("never", OK_TEXT)];
    const { code, results, logs } = await runMain(["--engine", ENGINE_FIXTURE, "--workers", "1"], lines);
    expect(code).toBe(EXIT_USAGE);
    expect(results).toEqual([{ id: "a", verdict: expected(OK_TEXT) }]);
    expect(logs.find((l) => l.level === "error")).toEqual(
      expect.objectContaining({ msg: "bad input line", line: 2, reason: "not valid JSON", service: "plantuml-engine" }),
    );
  }, TEST_TIMEOUT_MS);

  it("exits 2 on bad arguments without starting workers", async () => {
    const { code, logs, results } = await runMain([], [jobLine("a", OK_TEXT)]);
    expect(code).toBe(EXIT_USAGE);
    expect(results).toEqual([]);
    expect(logs).toHaveLength(1);
    expect(logs[0]).toMatchObject({ level: "error", msg: "usage: --engine <path> is required" });
  });

  it("exits 1 when the engine cannot load", async () => {
    const { code, results, logs } = await runMain(["--engine", "/nonexistent/e.json", "--workers", "1"], [
      jobLine("a", OK_TEXT),
    ]);
    expect(code).toBe(EXIT_FAILURE);
    expect(results).toEqual([]);
    expect(logs.some((l) => l.level === "error" && l.msg === "worker crashed")).toBe(true);
  }, TEST_TIMEOUT_MS);
});

describe("compiled cli.js", () => {
  const run = (args: string[], input: string) =>
    spawnSync(process.execPath, [built.cliPath, ...args], { input, encoding: "utf8", timeout: TEST_TIMEOUT_MS });

  it("streams 3 jobs from stdin to stdout in order and exits 0", () => {
    const input = [OK_TEXT, REJECT_TEXT, BETA_TEXT].map((t, i) => jobLine(`s${i}`, t)).join("\n") + "\n";
    const r = run(["--engine", ENGINE_FIXTURE, "--workers", "2"], input);
    expect(r.status).toBe(EXIT_OK);
    const out = r.stdout.split("\n").filter(Boolean).map((l) => JSON.parse(l));
    expect(out).toEqual([OK_TEXT, REJECT_TEXT, BETA_TEXT].map((t, i) => ({ id: `s${i}`, verdict: expected(t) })));
    expect(r.stderr).toContain('"msg":"end"');
  }, TEST_TIMEOUT_MS);

  it("exits 2 with an error JSON line on a malformed line", () => {
    const r = run(["--engine", ENGINE_FIXTURE, "--workers", "1"], "garbage\n");
    expect(r.status).toBe(EXIT_USAGE);
    const errLine = r.stderr.split("\n").filter(Boolean).map((l) => JSON.parse(l)).find((l) => l.level === "error");
    expect(errLine).toMatchObject({ msg: "bad input line", line: 1 });
  }, TEST_TIMEOUT_MS);
});
