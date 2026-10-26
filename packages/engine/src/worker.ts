// Node-only (D6): the worker_threads entry used by src/pool.ts (contract C6). It loads the
// engine once from `workerData.engine` and answers C6 job messages with I3 verdicts.
import { readFileSync } from "node:fs";
import { performance } from "node:perf_hooks";
import { pathToFileURL } from "node:url";
import { isMainThread, parentPort, workerData } from "node:worker_threads";
import { accepts, loadEngine } from "./index.js";
import type { EngineModel } from "./index.js";
import { errorVerdict, toWire } from "./pool.js";
import type { WireJob, WireResult, WorkerConfig, WorkerMessage } from "./pool.js";

const MS_PER_S = 1000;

/** Test seam (never set in production): runs before each job, inside the worker. */
export interface JobHook {
  beforeJob?: (job: WireJob) => void;
}

const messageOf = (err: unknown): string => (err instanceof Error ? err.message : String(err));

/** Judges one job. A throw becomes an `error` verdict for this job alone. */
export function handleJob(engine: EngineModel, job: WireJob, hook?: JobHook): WireResult {
  try {
    hook?.beforeJob?.(job);
    const verdict = accepts(engine, job.text, { raw: job.raw, timeoutMs: job.timeout_s * MS_PER_S });
    return { id: job.id, verdict: toWire(verdict) };
  } catch (err) {
    return { id: job.id, verdict: errorVerdict(messageOf(err)) };
  }
}

function patternCount(json: unknown): number {
  const patterns = (json as { patterns?: unknown }).patterns;
  return Array.isArray(patterns) ? patterns.length : 0;
}

/** Reads and loads the engine; the cause is wrapped so the pool sees the path. */
export function loadFromPath(path: string): { engine: EngineModel; patterns: number } {
  try {
    const json: unknown = JSON.parse(readFileSync(path, "utf8"));
    return { engine: loadEngine(json), patterns: patternCount(json) };
  } catch (err) {
    throw new Error(`cannot load engine ${path}: ${messageOf(err)}`, { cause: err });
  }
}

async function loadHook(path: string | null): Promise<JobHook | undefined> {
  return path === null ? undefined : ((await import(pathToFileURL(path).href)) as JobHook);
}

async function startWorker(config: WorkerConfig): Promise<void> {
  const port = parentPort;
  if (port === null) return;
  const t0 = performance.now();
  const { engine, patterns } = loadFromPath(config.engine);
  const hook = await loadHook(config.hook);
  const idle: WorkerMessage = { kind: "idle" };
  port.on("message", (job: WireJob) => {
    const msg: WorkerMessage = { kind: "result", result: handleJob(engine, job, hook) };
    port.postMessage(msg);
    // Immediates the job queued run first, so a crash they cause lands before `idle`.
    setImmediate(() => port.postMessage(idle));
  });
  const ready: WorkerMessage = { kind: "ready", load_ms: Math.round(performance.now() - t0), patterns };
  port.postMessage(ready);
}

if (!isMainThread && parentPort !== null) {
  void startWorker(workerData as WorkerConfig);
}
