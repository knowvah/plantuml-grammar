// Shared setup for the pool/CLI tests: compiles src/ once per test file so the worker and
// cli entry points exist as JavaScript, and builds jobs and loggers.
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import type { LogFields, WireJob } from "../../src/pool.js";

const PACKAGE_DIR = fileURLToPath(new URL("../../", import.meta.url));
export const ENGINE_FIXTURE = fileURLToPath(new URL("../fixtures/engine-toys.engine.json", import.meta.url));
export const HOOKS = fileURLToPath(new URL("./hooks.mjs", import.meta.url));
export const SLOW_START = fileURLToPath(new URL("./slow-start.mjs", import.meta.url));
export const TEST_TIMEOUT_MS = 60_000;

export interface Built {
  dir: string;
  workerUrl: URL;
  cliPath: string;
  cleanup: () => void;
}

export function buildEngine(): Built {
  const dir = mkdtempSync(join(tmpdir(), "engine-build-"));
  const tsc = join(dirname(createRequire(import.meta.url).resolve("typescript/package.json")), "bin", "tsc");
  execFileSync(process.execPath, [tsc, "-p", "tsconfig.json", "--outDir", dir], { cwd: PACKAGE_DIR });
  return {
    dir,
    workerUrl: pathToFileURL(join(dir, "worker.js")),
    cliPath: join(dir, "cli.js"),
    cleanup: () => rmSync(dir, { recursive: true, force: true }),
  };
}

export const job = (id: string, text: string, extra: Partial<WireJob> = {}): WireJob => ({
  id,
  text,
  raw: false,
  timeout_s: 30,
  ...extra,
});

export interface LogEntry extends LogFields {
  level: string;
  msg: string;
  ts: string;
  service: string;
}

export function collectLogs(): { log: (level: never, msg: string, f?: LogFields) => void; entries: LogEntry[] } {
  const entries: LogEntry[] = [];
  return {
    entries,
    log: (level, msg, fields = {}) => {
      entries.push({ level, msg, ts: "", service: "test", ...fields });
    },
  };
}

export async function* linesOf(lines: string[]): AsyncGenerator<string> {
  for (const l of lines) yield l;
}
