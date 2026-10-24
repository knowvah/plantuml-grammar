import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// D6 fitness test: the core must run in browsers, Electron and JCEF.
const SRC_DIR = fileURLToPath(new URL("../src", import.meta.url));
const NODE_ONLY = new Set(["cli.ts", "pool.ts", "worker.ts"]);
const FORBIDDEN: readonly { name: string; re: RegExp }[] = [
  { name: "node: import", re: /\bnode:/ },
  { name: "require(", re: /\brequire\(/ },
  { name: "process.", re: /\bprocess\./ },
  { name: "Buffer", re: /\bBuffer\b/ },
];

function coreFiles(dir: string): string[] {
  return readdirSync(dir)
    .filter((f) => f.endsWith(".ts") && !NODE_ONLY.has(f))
    .map((f) => join(dir, f));
}

function violations(files: readonly string[]): string[] {
  return files.flatMap((file) => {
    const text = readFileSync(file, "utf8");
    return FORBIDDEN.filter(({ re }) => re.test(text)).map(
      ({ name }) => `${file}: ${name}`,
    );
  });
}

describe("browser-safe core", () => {
  it("has no Node-only constructs in src/*.ts", () => {
    expect(violations(coreFiles(SRC_DIR))).toEqual([]);
  });

  it("detects each forbidden construct in a temporary offending file", () => {
    const dir = mkdtempSync(join(tmpdir(), "browser-safe-"));
    try {
      const file = join(dir, "bad.ts");
      writeFileSync(
        file,
        'import fs from "node:fs";\nconst r = require("x");\nprocess.exit();\nBuffer.from("");\n',
      );
      expect(violations([file])).toEqual([
        `${file}: node: import`,
        `${file}: require(`,
        `${file}: process.`,
        `${file}: Buffer`,
      ]);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("skips the Node-only entry files", () => {
    const dir = mkdtempSync(join(tmpdir(), "browser-safe-"));
    try {
      for (const f of ["cli.ts", "pool.ts", "worker.ts"]) {
        writeFileSync(join(dir, f), 'import "node:fs";\n');
      }
      writeFileSync(join(dir, "core.ts"), "export const x = 1;\n");
      expect(coreFiles(dir).map((p) => p.slice(dir.length + 1))).toEqual(["core.ts"]);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
