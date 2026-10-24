// Node-only (D6): a killable pool of worker_threads running src/worker.ts (decision D5,
// contract C6, plans/ts-engine/contracts.md#c6). Mirrors the error shape of
// tools/validate/parity_run.py:46-55 (`error_verdict`).
import { Worker } from "node:worker_threads";
import type { FirstFailure, Status, Verdict } from "./types.js";
import { STATUS_ERROR, STATUS_TIMEOUT } from "./types.js";

export const SERVICE_NAME = "plantuml-engine";
export const DEFAULT_KILL_GRACE_MS = 2000;
export const DEFAULT_TIMEOUT_S = 10;
const MS_PER_S = 1000;
const ERROR_LINE = 0;

/** One C6 job: the stdin line, validated. */
export interface WireJob {
  id: string;
  text: string;
  raw: boolean;
  timeout_s: number;
}

/** The I3 (snake_case) verdict emitted on the wire. */
export interface WireVerdict {
  accepted: boolean;
  diagram: string | null;
  first_failure: FirstFailure | null;
  model: string | null;
  status: Status;
}

export interface WireResult {
  id: string;
  verdict: WireVerdict;
}

/** Messages a worker posts to the pool. */
export type WorkerMessage =
  | { kind: "ready"; load_ms: number; patterns: number }
  | { kind: "result"; result: WireResult };

/** What the pool hands each worker through `workerData`. */
export interface WorkerConfig {
  engine: string;
  hook: string | null;
}

export type LogLevel = "debug" | "info" | "warn" | "error";
export type LogFields = Record<string, unknown>;
export type Logger = (level: LogLevel, msg: string, fields?: LogFields) => void;

/** A structured-JSON logger (`~/.claude/rules/logging.md`) over a line writer. */
export function jsonLogger(write: (line: string) => void): Logger {
  return (level, msg, fields = {}) => {
    write(`${JSON.stringify({ level, msg, ts: new Date().toISOString(), service: SERVICE_NAME, ...fields })}\n`);
  };
}

export function toWire(v: Verdict): WireVerdict {
  return {
    accepted: v.accepted,
    diagram: v.diagram,
    first_failure: v.firstFailure,
    model: v.model,
    status: v.status,
  };
}

/** A verdict for an engine crash, with the message in `first_failure.text`. */
export function errorVerdict(message: string): WireVerdict {
  return {
    accepted: false,
    diagram: null,
    first_failure: { line: ERROR_LINE, text: message },
    model: null,
    status: STATUS_ERROR,
  };
}

/** A verdict for a job whose worker was killed for overrunning its budget. */
export function timeoutVerdict(): WireVerdict {
  return { accepted: false, diagram: null, first_failure: null, model: null, status: STATUS_TIMEOUT };
}

export interface PoolOptions {
  /** Extra time past `timeout_s` before the worker is killed (D5). */
  killGraceMs?: number;
  log?: Logger;
  /** The worker script; defaults to `worker.js` next to this module. */
  workerUrl?: URL;
  /** Test seam: a module whose `beforeJob(job)` runs before every job in the worker. */
  hookModule?: string;
}

export interface PoolStart {
  patterns: number;
  loadMs: number;
}

interface Active {
  job: WireJob;
  resolve: (r: WireResult) => void;
  timer?: NodeJS.Timeout;
}

interface Slot {
  worker: Worker;
  ready: boolean;
  dead: boolean;
  current: Active | null;
}

interface Pending {
  job: WireJob;
  resolve: (r: WireResult) => void;
}

const messageOf = (err: unknown): string => (err instanceof Error ? err.message : String(err));

export class Pool {
  /** Resolves with the first worker's load stats, or `null` if the engine failed to load. */
  readonly started: Promise<PoolStart | null>;
  /** The load failure, once no worker could start. */
  fatal: string | null = null;
  private readonly slots = new Set<Slot>();
  private readonly queue: Pending[] = [];
  private readonly log: Logger;
  private readonly graceMs: number;
  private readonly workerUrl: URL;
  private readonly config: WorkerConfig;
  private closed = false;
  private announce: (s: PoolStart | null) => void = () => undefined;
  private announced = false;

  constructor(enginePath: string, size: number, opts: PoolOptions = {}) {
    this.log = opts.log ?? (() => undefined);
    this.graceMs = opts.killGraceMs ?? DEFAULT_KILL_GRACE_MS;
    this.workerUrl = opts.workerUrl ?? new URL("./worker.js", import.meta.url);
    this.config = { engine: enginePath, hook: opts.hookModule ?? null };
    this.started = new Promise((resolve) => {
      this.announce = resolve;
    });
    for (let i = 0; i < size; i++) this.spawn();
  }

  run(job: WireJob): Promise<WireResult> {
    if (this.fatal !== null || this.closed) {
      return Promise.resolve({ id: job.id, verdict: errorVerdict(this.fatal ?? "pool is closed") });
    }
    return new Promise((resolve) => {
      this.queue.push({ job, resolve });
      this.pump();
    });
  }

  async close(): Promise<void> {
    this.closed = true;
    this.settleStart(null);
    const stops = [...this.slots].map((slot) => this.retire(slot));
    this.slots.clear();
    await Promise.all(stops);
  }

  private spawn(): void {
    const worker = new Worker(this.workerUrl, { workerData: this.config });
    const slot: Slot = { worker, ready: false, dead: false, current: null };
    worker.on("message", (msg: WorkerMessage) => this.onMessage(slot, msg));
    worker.on("error", (err: unknown) => this.onFailure(slot, err instanceof Error ? err : new Error(String(err))));
    worker.on("exit", (code) => this.onFailure(slot, new Error(`worker exited with code ${code}`)));
    this.slots.add(slot);
  }

  private settleStart(s: PoolStart | null): void {
    if (this.announced) return;
    this.announced = true;
    this.announce(s);
  }

  private pump(): void {
    for (const slot of this.slots) {
      const next = this.queue[0];
      if (next === undefined) return;
      if (slot.current === null && !slot.dead) {
        this.queue.shift();
        slot.current = { job: next.job, resolve: next.resolve };
        slot.worker.postMessage(next.job);
        if (slot.ready) this.arm(slot);
      }
    }
  }

  /** Starts the kill timer; it only runs once the worker has loaded the engine. */
  private arm(slot: Slot): void {
    const active = slot.current;
    if (active === null) return;
    const budgetMs = active.job.timeout_s * MS_PER_S + this.graceMs;
    active.timer = setTimeout(() => this.kill(slot), budgetMs);
  }

  private onMessage(slot: Slot, msg: WorkerMessage): void {
    if (msg.kind === "ready") {
      slot.ready = true;
      this.log("info", "worker started", { load_ms: msg.load_ms, patterns: msg.patterns });
      this.settleStart({ patterns: msg.patterns, loadMs: msg.load_ms });
      this.arm(slot);
      return;
    }
    const active = slot.current;
    if (active === null) return;
    clearTimeout(active.timer);
    slot.current = null;
    active.resolve(msg.result);
    this.pump();
  }

  private kill(slot: Slot): void {
    const active = slot.current;
    if (slot.dead || active === null) return;
    this.log("warn", "worker killed for overrunning its budget", {
      id: active.job.id,
      timeout_s: active.job.timeout_s,
      grace_ms: this.graceMs,
    });
    slot.current = null;
    active.resolve({ id: active.job.id, verdict: timeoutVerdict() });
    this.replace(slot);
  }

  private onFailure(slot: Slot, err: Error): void {
    if (slot.dead) return;
    const active = slot.current;
    this.log("error", "worker crashed", { id: active?.job.id, error: err.message, stack: err.stack });
    slot.current = null;
    if (active !== null) {
      clearTimeout(active.timer);
      active.resolve({ id: active.job.id, verdict: errorVerdict(err.message) });
    }
    if (slot.ready) this.replace(slot);
    else this.failStartup(slot, err);
  }

  /** A worker that dies before loading the engine would respawn forever: fail the pool. */
  private failStartup(slot: Slot, err: Error): void {
    void this.retire(slot);
    this.slots.delete(slot);
    this.fatal = `engine failed to load: ${err.message}`;
    this.settleStart(null);
    for (const pending of this.queue.splice(0)) {
      pending.resolve({ id: pending.job.id, verdict: errorVerdict(this.fatal) });
    }
  }

  private replace(slot: Slot): void {
    void this.retire(slot);
    this.slots.delete(slot);
    if (this.closed) return;
    this.spawn();
    this.pump();
  }

  private async retire(slot: Slot): Promise<void> {
    slot.dead = true;
    clearTimeout(slot.current?.timer);
    try {
      await slot.worker.terminate();
    } catch (err) {
      this.log("error", "worker terminate failed", { error: messageOf(err) });
    }
  }
}
