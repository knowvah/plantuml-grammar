// Shared helpers for the TextMate proof tests (not a *.test.mjs file, so never run alone).
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import textmate from "vscode-textmate";
import oniguruma from "vscode-oniguruma";

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
export const ROOT = path.resolve(HERE, "..", "..", "..");
export const FIXTURES = HERE;
export const BUILD_DIR = path.join(ROOT, "build", "textmate");
export const SCOPE_NAME = "source.plantuml";
export const MODEL_DIR = path.join(FIXTURES, "model");

let onigLib;
function oniguruma_lib() {
  if (!onigLib) {
    const wasm = readFileSync(require.resolve("vscode-oniguruma/release/onig.wasm"));
    onigLib = oniguruma.loadWASM(wasm.buffer.slice(wasm.byteOffset, wasm.byteOffset + wasm.byteLength)).then(() => ({
      createOnigScanner: (sources) => new oniguruma.OnigScanner(sources),
      createOnigString: (s) => new oniguruma.OnigString(s),
    }));
  }
  return onigLib;
}

function run(command, args) {
  const result = spawnSync(command, args, { cwd: ROOT, encoding: "utf8" });
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(" ")} failed:\n${result.stderr}`);
  }
  return result.stdout;
}

/** Emit the grammar for the toy fixture models with the Python emitter; returns the parsed JSON. */
export function emitFixtureGrammar() {
  return emitGrammar(MODEL_DIR, "fixture.tmLanguage.json");
}

/** Emit the grammar for any model directory into build/textmate/<outName>; returns the parsed JSON. */
export function emitGrammar(modelDir, outName) {
  mkdirSync(BUILD_DIR, { recursive: true });
  const out = path.join(BUILD_DIR, outName);
  run("uv", ["run", "python", "-m", "tools.emit.textmate", "--model-dir", modelDir, "--out", out]);
  return JSON.parse(readFileSync(out, "utf8"));
}

/** True when model/generated holds at least one YAML model. */
export function hasGeneratedModels() {
  const dir = path.join(ROOT, "model", "generated");
  return existsSync(dir) && readdirSync(dir).some((f) => f.endsWith(".yaml"));
}

export const REAL_MODEL_DIR = path.join(ROOT, "model");

/** Convert a YAML tmLanguage file to an object (PyYAML via uv; avoids a JS YAML dependency). */
export function loadYamlGrammar(file) {
  const code = "import sys, json, yaml; print(json.dumps(yaml.safe_load(open(sys.argv[1], encoding='utf-8'))))";
  return JSON.parse(run("uv", ["run", "python", "-c", code, file]));
}

/** Load a grammar object into vscode-textmate; returns the grammar for its scopeName. */
export async function loadGrammar(raw) {
  const registry = new textmate.Registry({
    onigLib: oniguruma_lib(),
    loadGrammar: async (scopeName) =>
      scopeName === raw.scopeName ? textmate.parseRawGrammar(JSON.stringify(raw), "grammar.json") : null,
  });
  return registry.loadGrammar(raw.scopeName);
}

/** Tokenize text; returns [{line (1-based), start, end, text, scopes}]. */
export function tokenize(grammar, text) {
  const tokens = [];
  let stack = textmate.INITIAL;
  text.split("\n").forEach((line, index) => {
    const result = grammar.tokenizeLine(line, stack);
    for (const t of result.tokens) {
      tokens.push({
        line: index + 1,
        start: t.startIndex,
        end: Math.min(t.endIndex, line.length),
        text: line.slice(t.startIndex, t.endIndex),
        scopes: t.scopes,
      });
    }
    stack = result.ruleStack;
  });
  return tokens;
}

/** Names of the fixture .puml files (without extension). */
export function fixtureNames() {
  return readdirSync(FIXTURES)
    .filter((f) => f.endsWith(".puml"))
    .map((f) => f.slice(0, -".puml".length))
    .sort();
}

export function fixtureText(name) {
  return readFileSync(path.join(FIXTURES, `${name}.puml`), "utf8");
}

export function fixtureExpectations(name) {
  return JSON.parse(readFileSync(path.join(FIXTURES, `${name}.scopes.json`), "utf8"));
}

/** Every match/begin/end regex in a grammar, with the JSON path where it was found. */
export function collectRegexes(node, where = "$", found = []) {
  if (Array.isArray(node)) {
    node.forEach((item, i) => collectRegexes(item, `${where}[${i}]`, found));
  } else if (node && typeof node === "object") {
    for (const [key, value] of Object.entries(node)) {
      if (["match", "begin", "end"].includes(key) && typeof value === "string") {
        found.push({ where: `${where}.${key}`, regex: value });
      } else {
        collectRegexes(value, `${where}.${key}`, found);
      }
    }
  }
  return found;
}

/** Throws-free Oniguruma compile check; returns the entries that failed. */
export async function onigurumaFailures(regexes) {
  await oniguruma_lib();
  const failures = [];
  for (const { where, regex } of regexes) {
    try {
      new oniguruma.OnigScanner([regex]).dispose?.();
    } catch (error) {
      failures.push({ where, regex, error: String(error) });
    }
  }
  return failures;
}
