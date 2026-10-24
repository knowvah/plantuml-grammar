// Tests for src/pool.ts and src/worker.ts: the killable worker pool (D5, contract C6).
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { accepts } from "../src/index.js";
import { Pool, errorVerdict, jsonLogger, timeoutVerdict, toWire } from "../src/pool.js";
import type { Logger, PoolOptions } from "../src/pool.js";
import { handleJob, loadFromPath } from "../src/worker.js";
import { CRASH_AFTER, EXIT, EXIT_CODE, SPIN, THROW } from "./helpers/hooks.mjs";
import {
  ENGINE_FIXTURE,
  HOOKS,
  SLOW_START,
  TEST_TIMEOUT_MS,
  buildEngine,
  collectLogs,
  job,
} from "./helpers/pool-env.js";
import type { Built } from "./helpers/pool-env.js";
import { uml } from "./helpers/engine-fixtures.js";

const OK_TEXT = uml("alpha x");
const REJECT_TEXT = uml("zzz");
const { engine } = loadFromPath(ENGINE_FIXTURE);
const expected = (text: string) => toWire(accepts(engine, text));

let built: Built;
beforeAll(() => {
  built = buildEngine();
}, TEST_TIMEOUT_MS);
afterAll(() => built.cleanup());

function makePool(size: number, extra: PoolOptions = {}, enginePath = ENGINE_FIXTURE) {
  const logs = collectLogs();
  const pool = new Pool(enginePath, size, { workerUrl: built.workerUrl, log: logs.log as Logger, ...extra });
  return { pool, logs };
}

describe("verdict helpers", () => {
  it("shapes error and timeout verdicts like parity_run.error_verdict", () => {
    expect(errorVerdict("bad")).toEqual({
      accepted: false,
      diagram: null,
      first_failure: { line: 0, text: "bad" },
      model: null,
      status: "error",
    });
    expect(timeoutVerdict()).toEqual({
      accepted: false,
      diagram: null,
      first_failure: null,
      model: null,
      status: "timeout",
    });
  });

  it("writes one structured JSON line per log call", () => {
    const lines: string[] = [];
    jsonLogger((l) => lines.push(l))("warn", "hello", { id: "j1" });
    const entry = JSON.parse(lines[0] ?? "");
    expect(entry).toMatchObject({ level: "warn", msg: "hello", service: "plantuml-engine", id: "j1" });
    expect(entry.ts).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(lines[0]?.endsWith("\n")).toBe(true);
  });
});

describe("handleJob (in-process)", () => {
  it("returns the snake_case verdict equal to accepts", () => {
    expect(handleJob(engine, job("a", REJECT_TEXT))).toEqual({ id: "a", verdict: expected(REJECT_TEXT) });
    expect(expected(REJECT_TEXT).status).toBe("reject");
  });

  it("turns a throwing hook into an error verdict for that job", () => {
    const hook = {
      beforeJob: () => {
        throw new Error("hook failed");
      },
    };
    expect(handleJob(engine, job("b", OK_TEXT), hook).verdict).toEqual(errorVerdict("hook failed"));
    const nonError = {
      beforeJob: () => {
        throw "plain string"; // eslint-disable-line @typescript-eslint/only-throw-error
      },
    };
    expect(handleJob(engine, job("c", OK_TEXT), nonError).verdict.first_failure?.text).toBe("plain string");
  });

  it("wraps load failures with the path", () => {
    expect(() => loadFromPath("/nonexistent/engine.json")).toThrow(/cannot load engine \/nonexistent\/engine\.json/);
  });
});

describe("Pool", () => {
  it("answers jobs with verdicts equal to accepts and logs the load time", async () => {
    const { pool, logs } = makePool(2);
    try {
      const start = await pool.started;
      expect(start?.patterns).toBeGreaterThan(0);
      const texts = [OK_TEXT, uml("beta x", "beta y"), REJECT_TEXT, OK_TEXT, REJECT_TEXT];
      const results = await Promise.all(texts.map((t, i) => pool.run(job(`j${i}`, t))));
      expect(results.map((r) => r.id)).toEqual(["j0", "j1", "j2", "j3", "j4"]);
      expect(results.map((r) => r.verdict)).toEqual(texts.map(expected));
      const started = logs.entries.filter((e) => e.msg === "worker started");
      expect(started).toHaveLength(2);
      expect(started[0]).toMatchObject({ level: "info", patterns: start?.patterns });
      expect(typeof started[0]?.load_ms).toBe("number");
    } finally {
      await pool.close();
    }
  }, TEST_TIMEOUT_MS);

  it("kills an overrunning worker, reports timeout, warns, and keeps serving", async () => {
    const { pool, logs } = makePool(1, { hookModule: HOOKS, killGraceMs: 100 });
    try {
      await pool.started;
      const slow = await pool.run(job("slow", SPIN, { timeout_s: 0.2 }));
      expect(slow).toEqual({ id: "slow", verdict: timeoutVerdict() });
      const next = await pool.run(job("next", OK_TEXT));
      expect(next).toEqual({ id: "next", verdict: expected(OK_TEXT) });
      const warns = logs.entries.filter((e) => e.level === "warn");
      expect(warns).toHaveLength(1);
      expect(warns[0]).toMatchObject({ id: "slow", timeout_s: 0.2, grace_ms: 100 });
    } finally {
      await pool.close();
    }
  }, TEST_TIMEOUT_MS);

  it("does not count engine load time against the first job", async () => {
    const { pool } = makePool(1, { hookModule: SLOW_START, killGraceMs: 50 });
    try {
      const r = await pool.run(job("warm", OK_TEXT, { timeout_s: 0.1 }));
      expect(r).toEqual({ id: "warm", verdict: expected(OK_TEXT) });
    } finally {
      await pool.close();
    }
  }, TEST_TIMEOUT_MS);

  it("gives a job that throws status error, line 0, and leaves other jobs alone", async () => {
    const { pool, logs } = makePool(1, { hookModule: HOOKS });
    try {
      const [bad, good] = await Promise.all([pool.run(job("bad", THROW)), pool.run(job("good", OK_TEXT))]);
      expect(bad).toEqual({ id: "bad", verdict: errorVerdict("boom") });
      expect(good.verdict).toEqual(expected(OK_TEXT));
      expect(logs.entries.filter((e) => e.level === "error")).toEqual([]);
    } finally {
      await pool.close();
    }
  }, TEST_TIMEOUT_MS);

  it("reports a worker exit mid-job as an error verdict, logs the crash, and replaces it", async () => {
    const { pool, logs } = makePool(1, { hookModule: HOOKS });
    try {
      await pool.started;
      const dead = await pool.run(job("dead", EXIT));
      expect(dead).toEqual({ id: "dead", verdict: errorVerdict(`worker exited with code ${EXIT_CODE}`) });
      expect((await pool.run(job("after", REJECT_TEXT))).verdict).toEqual(expected(REJECT_TEXT));
      const crash = logs.entries.find((e) => e.level === "error");
      expect(crash).toMatchObject({ msg: "worker crashed", id: "dead" });
      expect(typeof crash?.stack).toBe("string");
    } finally {
      await pool.close();
    }
  }, TEST_TIMEOUT_MS);

  it("survives an uncaught error thrown after a job completes", async () => {
    const { pool, logs } = makePool(1, { hookModule: HOOKS });
    try {
      const first = await pool.run(job("late", CRASH_AFTER));
      expect(first.id).toBe("late");
      await vi.waitFor(() => expect(logs.entries.some((e) => e.msg === "worker crashed")).toBe(true));
      const second = await pool.run(job("next", OK_TEXT));
      expect(second.verdict).toEqual(expected(OK_TEXT));
      expect(logs.entries.some((e) => e.msg === "worker crashed")).toBe(true);
    } finally {
      await pool.close();
    }
  }, TEST_TIMEOUT_MS);

  it("fails every job with an error verdict when the engine cannot load", async () => {
    const { pool, logs } = makePool(2, {}, "/nonexistent/engine.json");
    try {
      expect(await pool.started).toBeNull();
      const r = await pool.run(job("x", OK_TEXT));
      expect(r.verdict.status).toBe("error");
      expect(r.verdict.first_failure?.text).toMatch(/^engine failed to load: cannot load engine \/nonexistent/);
      expect(pool.fatal).toContain("cannot load engine");
      expect(logs.entries.some((e) => e.level === "error" && e.msg === "worker crashed")).toBe(true);
    } finally {
      await pool.close();
    }
  }, TEST_TIMEOUT_MS);

  it("fails queued jobs when startup fails and rejects runs after close", async () => {
    const { pool } = makePool(1, {}, "/nonexistent/engine.json");
    const queued = pool.run(job("q", OK_TEXT));
    expect((await queued).verdict.status).toBe("error");
    await pool.close();
    expect((await pool.run(job("late", OK_TEXT))).verdict.first_failure?.text).toContain("cannot load engine");
    const { pool: p2 } = makePool(1);
    await p2.close();
    expect((await p2.run(job("late", OK_TEXT))).verdict.first_failure?.text).toBe("pool is closed");
  }, TEST_TIMEOUT_MS);
});
