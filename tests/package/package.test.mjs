// Packs packages/engine as @knowvah/plantuml-grammar, installs the tarball into a scratch
// project and uses it from there the way a consumer would (issue #1).
import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, SCOPE_NAME, loadGrammar, tokenize } from "../textmate/fixtures/helpers.mjs";

const PACKAGE_NAME = "@knowvah/plantuml-grammar";
const PACKAGE_DIR = path.join(ROOT, "packages", "engine");
const GRAMMAR = "plantuml.tmLanguage.json";
const ENGINE = "plantuml.engine.json";
const COPIED = [GRAMMAR, ENGINE, "LICENSE"];
const NODE_ONLY = /^package\/(dist|src)\/(cli|pool|worker)\./;

let scratch;
let entries;
let consumerRequire;

function run(command, args, cwd) {
  const result = spawnSync(command, args, { cwd, encoding: "utf8" });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${command} ${args.join(" ")} failed:\n${result.stderr}`);
  return result.stdout;
}

before(() => {
  scratch = mkdtempSync(path.join(tmpdir(), "plantuml-pack-"));
  run("npm", ["pack", "--pack-destination", scratch, "-w", "packages/engine"], ROOT);
  const tarball = path.join(scratch, readdirSync(scratch).find((f) => f.endsWith(".tgz")));
  entries = run("tar", ["-tzf", tarball], scratch).split("\n").filter(Boolean);
  const consumer = path.join(scratch, "consumer");
  mkdirSync(consumer);
  writeFileSync(path.join(consumer, "package.json"), '{ "name": "consumer", "private": true, "type": "module" }\n');
  run("npm", ["install", "--offline", "--no-audit", "--no-fund", tarball], consumer);
  consumerRequire = createRequire(path.join(consumer, "package.json"));
});

after(() => rmSync(scratch, { recursive: true, force: true }));

test("the tarball holds the grammar, the engine model and the browser-safe core only", () => {
  for (const file of [...COPIED, "README.md", "package.json", "dist/index.js", "dist/index.d.ts"]) {
    assert.ok(entries.includes(`package/${file}`), `missing ${file}`);
  }
  assert.deepEqual(entries.filter((e) => NODE_ONLY.test(e)), []);
  assert.deepEqual(entries.filter((e) => e.includes("/test/") || e.endsWith(".test.ts")), []);
});

test("packing leaves no copied files behind in the workspace", () => {
  assert.deepEqual(COPIED.filter((f) => existsSync(path.join(PACKAGE_DIR, f))), []);
});

test("the published manifest is public and versioned by the release", () => {
  const manifest = JSON.parse(readFileSync(consumerRequire.resolve(`${PACKAGE_NAME}/package.json`), "utf8"));
  assert.equal(manifest.name, PACKAGE_NAME);
  assert.equal(manifest.private, undefined);
  assert.equal(manifest.version, "0.0.0-development");
});

test("the grammar resolves, matches dist/ and tokenizes with vscode-textmate", async () => {
  const file = consumerRequire.resolve(`${PACKAGE_NAME}/${GRAMMAR}`);
  assert.equal(readFileSync(file, "utf8"), readFileSync(path.join(ROOT, "dist", GRAMMAR), "utf8"));
  const raw = JSON.parse(readFileSync(file, "utf8"));
  assert.equal(raw.scopeName, SCOPE_NAME);
  const [start] = tokenize(await loadGrammar(raw), "@startuml\nAlice -> Bob : hello\n@enduml\n");
  assert.ok(start.scopes.includes("keyword.control.start.plantuml"), start.scopes.join(" "));
});

test("the engine judges diagrams with the bundled model", async () => {
  const { accepts, loadEngine } = await import(pathToFileURL(consumerRequire.resolve(PACKAGE_NAME)).href);
  const model = JSON.parse(readFileSync(consumerRequire.resolve(`${PACKAGE_NAME}/${ENGINE}`), "utf8"));
  const engine = loadEngine(model);
  assert.deepEqual(accepts(engine, "@startuml\nAlice -> Bob : hello\n@enduml"), {
    accepted: true,
    diagram: "SEQUENCE",
    model: "sequence",
    status: "ok",
    firstFailure: null,
  });
  assert.deepEqual(accepts(engine, "@startuml\n)(*&^\n@enduml").firstFailure, { line: 2, text: ")(*&^" });
});
