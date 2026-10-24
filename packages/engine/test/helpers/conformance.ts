// Helpers for test/conformance.test.ts: golden parsing, verdict comparison and the
// mismatch table. Reads repo files outside the package (decision D6); test-only.
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { Interpreter } from "../../src/engine.js";
import { loadEngine } from "../../src/load.js";
import type { EngineModel } from "../../src/load.js";
import { splitBlocks } from "../../src/source.js";
import type { Verdict } from "../../src/types.js";

export const ROOT_ENV = "PLANTUML_GRAMMAR_ROOT";
export const FIXTURES_GOLDEN = "tests/conformance/fixtures.jsonl";
export const TOY_DIR = "tests/conformance/toy";
export const ENGINE_FILE = "dist/plantuml.engine.json";
export const TOY_PREFIX = "toy/";
export const MAX_TABLE_ROWS = 50;
/** Verdict fields compared, in Python's snake_case spelling (decision D9). */
export const FIELDS = ["accepted", "diagram", "model", "status", "first_failure"] as const;
export type Field = (typeof FIELDS)[number];

/**
 * Cases that reach a D3 fallback rule, as `<fixture>#<block>#<raw>` -> reason. Empty: no
 * pattern is unsupported, so nothing is excused.
 */
export const EXPECTED_FALLBACKS: ReadonlyMap<string, string> = new Map();

export type PyVerdict = Record<Field, unknown>;

export interface Golden {
  readonly fixture: string;
  readonly block: number;
  readonly raw: boolean;
  readonly text?: string;
  readonly start_map?: Record<string, string[]>;
  readonly verdict: PyVerdict;
}

export interface Mismatch {
  readonly fixture: string;
  readonly block: number;
  readonly raw: boolean;
  readonly field: Field;
  readonly python: unknown;
  readonly ts: unknown;
}

export type Located = { found: true; root: string } | { found: false; reason: string };

const PACKAGE_DIR = dirname(dirname(dirname(fileURLToPath(import.meta.url))));

export function repoRoot(env: NodeJS.ProcessEnv = process.env): string {
  const override = env[ROOT_ENV];
  return override !== undefined && override !== "" ? resolve(override) : resolve(PACKAGE_DIR, "../..");
}

/** Checks the goldens and the engine JSON exist under `root`; says what is missing. */
export function locate(root: string): Located {
  const needed = [FIXTURES_GOLDEN, ENGINE_FILE, TOY_DIR];
  const missing = needed.filter((rel) => !existsSync(join(root, rel)));
  if (missing.length === 0) return { found: true, root };
  return { found: false, reason: `conformance skipped: ${missing.join(", ")} not found under ${root}` };
}

export function parseGoldens(jsonl: string): Golden[] {
  return jsonl
    .split("\n")
    .filter((line) => line.trim() !== "")
    .map((line) => JSON.parse(line) as Golden);
}

/** Python's `read_text(encoding="utf-8", errors="replace")`: universal newlines, BOM kept. */
export function readPythonText(path: string): string {
  return readFileSync(path).toString("utf8").replace(/\r\n|\r/g, "\n");
}

export function snake(verdict: Verdict): PyVerdict {
  return {
    accepted: verdict.accepted,
    diagram: verdict.diagram,
    model: verdict.model,
    status: verdict.status,
    first_failure: verdict.firstFailure,
  };
}

/** Field-by-field differences between a golden and the TS verdict. */
export function compareVerdict(golden: Golden, ts: Verdict): Mismatch[] {
  const mine = snake(ts);
  const { fixture, block, raw } = golden;
  return FIELDS.filter((f) => JSON.stringify(golden.verdict[f]) !== JSON.stringify(mine[f])).map((field) => ({
    fixture,
    block,
    raw,
    field,
    python: golden.verdict[field],
    ts: mine[field],
  }));
}

export function formatTable(mismatches: readonly Mismatch[], total: number): string {
  const rows = mismatches.slice(0, MAX_TABLE_ROWS).map((m) =>
    [m.fixture, m.block, m.raw, m.field, JSON.stringify(m.python), JSON.stringify(m.ts)].join(" | "),
  );
  const head = "fixture | block | raw | field | python | ts";
  return [`${mismatches.length} mismatching fields in ${total} cases`, head, ...rows].join("\n");
}

/** Caches one interpreter per (engine, start map); compiled rules persist across cases. */
export class InterpreterCache {
  readonly #slots = new Map<string, Interpreter>();

  constructor(private readonly engine: EngineModel) {}

  get(startMap: Record<string, string[]> | undefined): Interpreter {
    const key = JSON.stringify(startMap ?? null);
    let found = this.#slots.get(key);
    if (found === undefined) {
      found = new Interpreter(this.engine, startMap === undefined ? {} : { startMap });
      this.#slots.set(key, found);
    }
    return found;
  }
}

/** Block text of a golden: its own `text` (toy), else block `block` of the fixture file. */
export function blockText(golden: Golden, blocksOf: (fixture: string) => string[]): string {
  if (golden.text !== undefined) return golden.text;
  const text = blocksOf(golden.fixture)[golden.block];
  if (text === undefined) throw new Error(`${golden.fixture} has no block ${golden.block}`);
  return text;
}

export function excused(golden: Golden): boolean {
  return EXPECTED_FALLBACKS.has(`${golden.fixture}#${golden.block}#${golden.raw}`);
}

/** Runs every golden through the interpreter and collects the differences. */
export function runGoldens(
  goldens: readonly Golden[],
  interpreters: InterpreterCache,
  blocksOf: (fixture: string) => string[],
): Mismatch[] {
  const out: Mismatch[] = [];
  for (const golden of goldens) {
    if (excused(golden)) continue;
    const verdict = interpreters.get(golden.start_map).accepts(blockText(golden, blocksOf), { raw: golden.raw });
    out.push(...compareVerdict(golden, verdict));
  }
  return out;
}

/** Memoised `splitBlocks` of the fixture files under `root`. */
export function blockSplitter(root: string): (fixture: string) => string[] {
  const cache = new Map<string, string[]>();
  return (fixture) => {
    let blocks = cache.get(fixture);
    if (blocks === undefined) {
      blocks = splitBlocks(readPythonText(join(root, fixture)));
      cache.set(fixture, blocks);
    }
    return blocks;
  };
}

export function readEngine(path: string): EngineModel {
  return loadEngine(JSON.parse(readFileSync(path, "utf8")));
}

export function toyNames(root: string): string[] {
  return readdirSync(join(root, TOY_DIR))
    .filter((f) => f.endsWith(".jsonl"))
    .map((f) => f.slice(0, -".jsonl".length))
    .sort();
}

/** Groups goldens by the second path segment under `tests/fixtures` (the family). */
export function groupByFamily(goldens: readonly Golden[]): Map<string, Golden[]> {
  const groups = new Map<string, Golden[]>();
  for (const g of goldens) {
    const family = g.fixture.split("/")[2] ?? g.fixture;
    groups.set(family, [...(groups.get(family) ?? []), g]);
  }
  return groups;
}
