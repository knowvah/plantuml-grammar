// Shared setup for the engine tests: fixture loading and verdict helpers.
import { readFileSync } from "node:fs";
import { expect } from "vitest";
import { accepts, loadEngine } from "../../src/index.js";
import type { EngineModel, Verdict } from "../../src/index.js";

const FIXTURES = new URL("../fixtures/", import.meta.url);
export const END_LINE = "@enduml";

export const readJson = (name: string): Record<string, unknown> =>
  JSON.parse(readFileSync(new URL(`engine-${name}.engine.json`, FIXTURES), "utf8"));
export const load = (name: string): EngineModel => loadEngine(readJson(name));

export const uml = (...lines: string[]): string => ["@startuml", ...lines, END_LINE].join("\n");
export const only = (id: string): { startMap: Record<string, string[]> } => ({
  startMap: { uml: [id] },
});

export function failureOf(v: Verdict): [number, string] {
  expect(v.firstFailure).not.toBeNull();
  return [v.firstFailure?.line ?? -1, v.firstFailure?.text ?? ""];
}

/** `run(id, ...lines)`: `[accepted, failure]` of a uml block against model `id`. */
export function runner(engine: EngineModel): (id: string, ...lines: string[]) => [boolean, [number, string] | null] {
  return (id, ...lines) => {
    const v = accepts(engine, uml(...lines), only(id));
    return [v.accepted, v.accepted ? null : failureOf(v)];
  };
}
