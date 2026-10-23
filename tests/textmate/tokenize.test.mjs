import { test } from "node:test";
import assert from "node:assert/strict";
import {
  collectRegexes,
  REAL_MODEL_DIR,
  emitFixtureGrammar,
  emitGrammar,
  fixtureExpectations,
  fixtureNames,
  fixtureText,
  hasGeneratedModels,
  loadGrammar,
  onigurumaFailures,
  tokenize,
} from "./fixtures/helpers.mjs";

const rawGrammar = emitFixtureGrammar();
const grammar = await loadGrammar(rawGrammar);

function findScope(tokens, { line, text, scope }) {
  return tokens.some((t) => t.line === line && t.text.includes(text) && t.scopes.includes(scope));
}

test("every emitted regex compiles under Oniguruma", async () => {
  const regexes = collectRegexes(rawGrammar);
  assert.ok(regexes.length >= 15, `expected many regexes, got ${regexes.length}`);
  assert.deepEqual(await onigurumaFailures(regexes), []);
});

test("fixture directory holds the expected inputs", () => {
  assert.deepEqual(fixtureNames(), ["class", "sequence"]);
});

for (const name of fixtureNames()) {
  test(`fixture ${name}: expected scopes on chosen tokens`, () => {
    const tokens = tokenize(grammar, fixtureText(name));
    const missing = fixtureExpectations(name).filter((e) => !findScope(tokens, e));
    assert.deepEqual(missing, []);
  });
}

test("class line gets keyword, entity name and color scopes", () => {
  const tokens = tokenize(grammar, "@startuml\nclass Foo <<entity>> #red\n@enduml\n");
  const line = tokens.filter((t) => t.line === 2);
  const scopesOf = (text) => line.find((t) => t.text === text).scopes;
  assert.ok(scopesOf("class").some((s) => s.startsWith("keyword")));
  assert.ok(scopesOf("Foo").some((s) => s.startsWith("entity.name")));
  assert.ok(scopesOf("#red").some((s) => s.startsWith("constant.other.color")));
});

test("text outside a diagram block is not tokenized as a command", () => {
  const tokens = tokenize(grammar, "class Foo");
  assert.deepEqual(tokens.map((t) => t.scopes), [["source.plantuml"]]);
});

test("package body ends at the popping rule", () => {
  const tokens = tokenize(grammar, "@startuml\npackage p {\nitem A\n}\nclass Z\n@enduml\n");
  const z = tokens.find((t) => t.line === 5 && t.text === "Z");
  assert.ok(z.scopes.includes("entity.name.type.plantuml"));
  const item = tokens.find((t) => t.line === 3 && t.text === "item");
  assert.ok(item.scopes.includes("keyword.other.plantuml"));
});

test("the Oniguruma check reports an invalid regex", async () => {
  const failures = await onigurumaFailures([{ where: "$.bad", regex: "(unclosed" }]);
  assert.deepEqual(failures.map((f) => f.where), ["$.bad"]);
});

test(
  "every regex emitted from model/generated compiles under Oniguruma",
  { skip: hasGeneratedModels() ? false : "model/generated is empty" },
  async () => {
    const regexes = collectRegexes(emitGrammar(REAL_MODEL_DIR, "real.tmLanguage.json"));
    assert.ok(regexes.length > 100, `got ${regexes.length} regexes`);
    assert.deepEqual(await onigurumaFailures(regexes), []);
  },
);
