// Node-only (D6): JSONL front end for the engine (contract C6, decision D8). Run as
// `node packages/engine/dist/cli.js --engine <path> [--workers N]`; `package.json` has no
// `bin` entry because it belongs to T4 (decision logged in the T15 hand-back).
import { realpathSync } from "node:fs";
import { availableParallelism } from "node:os";
import { createInterface } from "node:readline";
import { pathToFileURL } from "node:url";
import { parseArgs } from "node:util";
import { DEFAULT_TIMEOUT_S, Pool, jsonLogger } from "./pool.js";
import type { Logger, PoolOptions, WireJob, WireResult } from "./pool.js";

export const EXIT_OK = 0;
export const EXIT_FAILURE = 1;
export const EXIT_USAGE = 2;
const IN_FLIGHT_PER_WORKER = 4;

export type Parsed<T> = { ok: true; value: T } | { ok: false; message: string };

export interface CliArgs {
  engine: string;
  workers: number;
}

export function parseCliArgs(argv: string[], defaultWorkers: number): Parsed<CliArgs> {
  let values: { engine?: string | undefined; workers?: string | undefined };
  try {
    values = parseArgs({
      args: argv,
      options: { engine: { type: "string" }, workers: { type: "string" } },
      strict: true,
    }).values;
  } catch (err) {
    return { ok: false, message: `usage: --engine <path> [--workers N] (${(err as Error).message})` };
  }
  if (values.engine === undefined) return { ok: false, message: "usage: --engine <path> is required" };
  const workers = values.workers === undefined ? defaultWorkers : Number(values.workers);
  if (!Number.isInteger(workers) || workers < 1) {
    return { ok: false, message: "usage: --workers must be a positive integer" };
  }
  return { ok: true, value: { engine: values.engine, workers } };
}

const isPositive = (v: unknown): v is number => typeof v === "number" && v > 0;

/** The first reason an object is not a C6 job, or null. Reasons never echo block text. */
function jobProblem(o: Record<string, unknown>): string | null {
  if (typeof o.id !== "string") return "id must be a string";
  if (typeof o.text !== "string") return "text must be a string";
  if (o.raw !== undefined && typeof o.raw !== "boolean") return "raw must be a boolean";
  if (o.timeout_s !== undefined && !isPositive(o.timeout_s)) return "timeout_s must be a positive number";
  return null;
}

/** Validates one stdin line. Reasons never echo the line (it holds block text). */
export function parseJobLine(line: string): Parsed<WireJob> {
  let raw: unknown;
  try {
    raw = JSON.parse(line);
  } catch {
    return { ok: false, message: "not valid JSON" };
  }
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return { ok: false, message: "job must be a JSON object" };
  const o = raw as Record<string, unknown>;
  const problem = jobProblem(o);
  if (problem !== null) return { ok: false, message: problem };
  return {
    ok: true,
    value: {
      id: o.id as string,
      text: o.text as string,
      raw: (o.raw as boolean | undefined) ?? false,
      timeout_s: (o.timeout_s as number | undefined) ?? DEFAULT_TIMEOUT_S,
    },
  };
}

export interface CliIo {
  lines: AsyncIterable<string>;
  stdout: (s: string) => void;
  stderr: (s: string) => void;
  poolOptions?: PoolOptions;
  /** Defaults to `os.availableParallelism()`. */
  defaultWorkers?: number;
}

interface RunSummary {
  jobs: number;
  statuses: Record<string, number>;
  badLine: boolean;
}

/** Submits jobs as lines arrive and emits results in input order, bounding in-flight work. */
async function streamJobs(io: CliIo, pool: Pool, log: Logger, limit: number): Promise<RunSummary> {
  const summary: RunSummary = { jobs: 0, statuses: {}, badLine: false };
  const inflight: Promise<WireResult>[] = [];
  const emit = async (): Promise<void> => {
    const result = await inflight.shift();
    if (result === undefined) return;
    const status = result.verdict.status;
    summary.statuses[status] = (summary.statuses[status] ?? 0) + 1;
    io.stdout(`${JSON.stringify(result)}\n`);
  };
  let lineNo = 0;
  for await (const line of io.lines) {
    lineNo++;
    if (line.trim() === "") continue;
    const parsed = parseJobLine(line);
    if (!parsed.ok) {
      log("error", "bad input line", { line: lineNo, reason: parsed.message });
      summary.badLine = true;
      break;
    }
    summary.jobs++;
    inflight.push(pool.run(parsed.value));
    if (inflight.length >= limit) await emit();
  }
  while (inflight.length > 0) await emit();
  return summary;
}

export async function main(argv: string[], io: CliIo): Promise<number> {
  const log = jsonLogger(io.stderr);
  const args = parseCliArgs(argv, io.defaultWorkers ?? availableParallelism());
  if (!args.ok) {
    log("error", args.message);
    return EXIT_USAGE;
  }
  const { engine, workers } = args.value;
  const t0 = performance.now();
  const pool = new Pool(engine, workers, { ...io.poolOptions, log });
  try {
    const start = await pool.started;
    if (start === null) return EXIT_FAILURE;
    log("info", "start", { engine, workers, patterns: start.patterns, load_ms: start.loadMs });
    const summary = await streamJobs(io, pool, log, workers * IN_FLIGHT_PER_WORKER);
    const wallMs = Math.round(performance.now() - t0);
    log("info", "end", { jobs: summary.jobs, statuses: summary.statuses, wall_ms: wallMs });
    return summary.badLine ? EXIT_USAGE : EXIT_OK;
  } finally {
    await pool.close();
  }
}

function isEntryPoint(): boolean {
  const entry = process.argv[1];
  return entry !== undefined && import.meta.url === pathToFileURL(realpathSync(entry)).href;
}

if (isEntryPoint()) {
  // Subscribe now: readline drops lines emitted before the async iterator is created, and
  // `main` awaits the pool before it reads.
  const iterator = createInterface({ input: process.stdin, crlfDelay: Infinity })[Symbol.asyncIterator]();
  const lines: AsyncIterable<string> = { [Symbol.asyncIterator]: () => iterator };
  void main(process.argv.slice(2), {
    lines,
    stdout: (s) => process.stdout.write(s),
    stderr: (s) => process.stderr.write(s),
  }).then((code) => {
    process.exitCode = code;
  });
}
