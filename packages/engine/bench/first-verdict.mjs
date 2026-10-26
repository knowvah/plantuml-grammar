// First-verdict latency per diagram family (#4). V8 compiles a regex on its first
// execution and recompiles it to native code on the next one, so the first and second
// `accepts` of a family cost far more than later calls. Each sample runs in a fresh
// process: load the engine, then judge the family's block twice.
//
//   npm run build -w packages/engine
//   node packages/engine/bench/first-verdict.mjs [--runs 5] [--patterns] [--json] [FAMILY...]
//
// Samples: the first accepted, non-raw conformance golden of each diagram family
// (tests/conformance/fixtures.jsonl). Timings vary with the machine; this is a report,
// not a test.
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { performance } from "node:perf_hooks";
import { fileURLToPath } from "node:url";

const REPO = fileURLToPath(new URL("../../../", import.meta.url));
const ENGINE_JSON = `${REPO}dist/plantuml.engine.json`;
const GOLDENS = `${REPO}tests/conformance/fixtures.jsonl`;
const DIST = new URL("../dist/", import.meta.url);
const TOP_PATTERNS = 3;

/** `{family: blockText}`: the first accepted, non-raw golden of each diagram family. */
async function samples() {
  const { splitBlocks } = await import(new URL("source.js", DIST).href);
  const out = {};
  for (const line of readFileSync(GOLDENS, "utf8").split("\n")) {
    if (line === "") continue;
    const { fixture, block, raw, verdict } = JSON.parse(line);
    if (raw || !verdict.accepted || verdict.diagram === null || verdict.diagram in out) continue;
    const text = splitBlocks(readFileSync(`${REPO}${fixture}`, "utf8"))[block];
    if (text !== undefined) out[verdict.diagram] = text;
  }
  return out;
}

/** Wraps `RegExp.prototype.test` to time each engine regex; returns the stats map. */
function instrument() {
  const stats = new Map();
  const test = RegExp.prototype.test;
  RegExp.prototype.test = function timed(s) {
    const t = performance.now();
    const result = test.call(this, s);
    stats.get(this)?.calls.push(performance.now() - t);
    return result;
  };
  const compile = (source, flags) => {
    const re = new RegExp(source, flags);
    stats.set(re, { bytes: Buffer.byteLength(source), calls: [] });
    return re;
  };
  return { stats, compile };
}

function topPatterns(stats) {
  return [...stats.values()]
    .filter((s) => s.calls.length > 0)
    .map((s) => ({ bytes: s.bytes, ms: round(s.calls.reduce((a, b) => a + b, 0)) }))
    .sort((a, b) => b.ms - a.ms)
    .slice(0, TOP_PATTERNS);
}

/** Child: one family in this process; prints one JSON line. */
async function child(family, text, withPatterns) {
  const probe = withPatterns ? instrument() : null;
  const t0 = performance.now();
  const { loadEngine, accepts } = await import(new URL("index.js", DIST).href);
  const options = probe === null ? {} : { compile: probe.compile };
  const engine = loadEngine(JSON.parse(readFileSync(ENGINE_JSON, "utf8")), options);
  const t1 = performance.now();
  const first = accepts(engine, text);
  const t2 = performance.now();
  accepts(engine, text);
  const t3 = performance.now();
  const row = { family, load: t1 - t0, first: t2 - t1, second: t3 - t2, ok: first.accepted };
  if (probe !== null) row.patterns = topPatterns(probe.stats);
  process.stdout.write(`${JSON.stringify(row)}\n`);
}

function round(ms) {
  return Math.round(ms * 10) / 10;
}

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/** Runs one fresh child process; the block text goes in on stdin. */
function spawn(family, text, withPatterns) {
  const args = [fileURLToPath(import.meta.url), "--child", family];
  if (withPatterns) args.push("--patterns");
  return JSON.parse(execFileSync(process.execPath, args, { encoding: "utf8", input: text }));
}

/** Median load/first/second of `runs` fresh processes; patterns from the last run. */
function measure(family, text, runs, withPatterns) {
  const rows = Array.from({ length: runs }, (_, i) => spawn(family, text, withPatterns && i === runs - 1));
  const summary = { family, runs, ok: rows.every((r) => r.ok) };
  for (const key of ["load", "first", "second"]) summary[key] = round(median(rows.map((r) => r[key])));
  if (withPatterns) summary.patterns = rows.at(-1).patterns;
  return summary;
}

function row(r) {
  const cells = [r.load, r.first, r.second].map((v) => String(v).padStart(9));
  const patterns = (r.patterns ?? []).map((p) => `${p.bytes} B ${p.ms} ms`);
  const tail = patterns.length > 0 ? ["", patterns.join(", ")] : [];
  return [r.family.padEnd(12), ...cells, r.ok ? " yes" : " NO", ...tail].join(" ");
}

function table(results) {
  return ["family        load ms  first ms  second ms  ok", ...results.map(row)].join("\n");
}

function parseArgs(argv) {
  const opts = { runs: 5, patterns: false, json: false, families: [], child: null };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--runs") opts.runs = Number(argv[++i]);
    else if (arg === "--patterns") opts.patterns = true;
    else if (arg === "--json") opts.json = true;
    else if (arg === "--child") opts.child = argv[++i];
    else opts.families.push(arg);
  }
  if (!Number.isInteger(opts.runs) || opts.runs < 1) throw new Error("--runs must be a positive integer");
  return opts;
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  // The child reads its block from stdin, so nothing of the engine loads before timing.
  if (opts.child !== null) return child(opts.child, readFileSync(0, "utf8"), opts.patterns);
  const all = await samples();
  const unknown = opts.families.filter((f) => !(f in all));
  if (unknown.length > 0) throw new Error(`no sample for: ${unknown.join(", ")}`);
  const families = opts.families.length > 0 ? opts.families : Object.keys(all);
  const results = families.map((f) => measure(f, all[f], opts.runs, opts.patterns));
  results.sort((a, b) => b.first - a.first);
  console.log(opts.json ? JSON.stringify(results, null, 2) : table(results));
}

await main();
