// Compares our emitted grammar with vscode-plantuml's on the shared fixtures.
// Coarseness is reported (to build/textmate-coarseness.json), never asserted.
import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  ROOT,
  emitFixtureGrammar,
  fixtureNames,
  fixtureText,
  loadGrammar,
  loadYamlGrammar,
  tokenize,
} from "./fixtures/helpers.mjs";

const BASELINE_PATH =
  process.env.VSCODE_PLANTUML_GRAMMAR ??
  path.join(os.homedir(), "git", "qjebbs", "vscode-plantuml", "syntaxes", "plantuml.yaml-tmLanguage");
const REPORT_PATH = path.join(ROOT, "build", "textmate-coarseness.json");
const BASELINE_ROOT_DEPTH = 1;

function visibleOverlaps(token, others) {
  return others.filter((o) => o.line === token.line && o.start < token.end && o.end > token.start);
}

/** Baseline tokens (non-blank, deeper than the root scope) where every overlapping token of ours has fewer scopes. */
export function coarserTokens(ours, baseline) {
  const found = [];
  for (const token of baseline) {
    if (token.text.trim() === "" || token.scopes.length <= BASELINE_ROOT_DEPTH) continue;
    const overlaps = visibleOverlaps(token, ours);
    if (overlaps.length > 0 && overlaps.every((o) => o.scopes.length < token.scopes.length)) {
      found.push({
        line: token.line,
        text: token.text.trim(),
        ours: overlaps[0].scopes,
        baseline: token.scopes,
      });
    }
  }
  return found;
}

test("coarseness helper flags only tokens with fewer scopes", () => {
  const mk = (scopes, start = 0) => ({ line: 1, start, end: start + 3, text: "abc", scopes });
  assert.deepEqual(coarserTokens([mk(["a"])], [mk(["x", "y"])]), [
    { line: 1, text: "abc", ours: ["a"], baseline: ["x", "y"] },
  ]);
  assert.deepEqual(coarserTokens([mk(["a", "b"])], [mk(["x", "y"])]), []);
  assert.deepEqual(coarserTokens([mk(["a"])], [mk(["x"])]), []);
});

const skip = existsSync(BASELINE_PATH)
  ? false
  : `vscode-plantuml grammar not found at ${BASELINE_PATH} (set VSCODE_PLANTUML_GRAMMAR to override)`;

test("baseline comparison writes a coarseness report", { skip }, async () => {
  const ours = await loadGrammar(emitFixtureGrammar());
  const baseline = await loadGrammar(loadYamlGrammar(BASELINE_PATH));
  const report = { baseline: BASELINE_PATH, fixtures: {} };
  for (const name of fixtureNames()) {
    const text = fixtureText(name);
    const coarser = coarserTokens(tokenize(ours, text), tokenize(baseline, text));
    report.fixtures[name] = { coarserTokenCount: coarser.length, tokens: coarser };
  }
  mkdirSync(path.dirname(REPORT_PATH), { recursive: true });
  writeFileSync(REPORT_PATH, JSON.stringify(report, null, 2) + "\n");
  console.log(`coarseness report: ${REPORT_PATH}`);
  assert.deepEqual(Object.keys(report.fixtures), fixtureNames());
});
