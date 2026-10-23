import { test } from "node:test";
import assert from "node:assert/strict";
import textmate from "vscode-textmate";
import oniguruma from "vscode-oniguruma";

test("vscode-textmate and vscode-oniguruma import", () => {
  assert.equal(typeof textmate.Registry, "function");
  assert.equal(typeof oniguruma.loadWASM, "function");
});
