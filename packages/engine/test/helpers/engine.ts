import { loadEngine } from "../../src/load.js";
import type { EngineModel } from "../../src/load.js";
import { JOINER } from "../../src/scan.js";
import type { EngineJson, EntryJson, PatternJson } from "../../src/types.js";
import type { Line } from "../../src/source.js";

export const MODEL_ID = "toy";
export const MAIN = "main";

export function lines(...texts: string[]): Line[] {
  return texts.map((text, index) => ({ number: index + 1, text, trimmed: text.trim() }));
}

export function entry(partial: Partial<EntryJson> & Pick<EntryJson, "start">): EntryJson {
  return {
    command: "Cmd",
    kind: "single",
    action: "",
    target: "",
    require_pop: false,
    reject: false,
    gives: "",
    needs: "",
    untrimmed: false,
    ...partial,
  };
}

/** One-model engine whose `main` context holds `entries`; `sources` are whole-line patterns. */
export function toyEngine(
  sources: readonly string[],
  entries: readonly EntryJson[],
  glueUnits = true,
): EngineModel {
  const patterns = sources.map((source): PatternJson => ({ source: `^(?:${source})$`, flags: "u" }));
  return engineJson(patterns, entries, glueUnits);
}

/** Same, with the pattern table given verbatim (splits, sticky heads, unions). */
export function engineJson(
  patterns: readonly PatternJson[],
  entries: readonly EntryJson[],
  glueUnits = true,
): EngineModel {
  const json: EngineJson = {
    engine_format: 1,
    pin: "0".repeat(40),
    patterns: [...patterns],
    context_table: [[...entries]],
    models: {
      [MODEL_ID]: {
        layer: "diagram",
        diagram: "CLASS",
        factory: "F",
        glue_units: glueUnits,
        empty_needs_end: false,
        start_map: {},
        includes: [],
        contexts: { [MAIN]: 0 },
      },
    },
    model_order: [MODEL_ID],
    tops: { F: MODEL_ID },
  };
  return loadEngine(json);
}

export const STYLE_START = `<style>(?:${JOINER}[a-z]+)*${JOINER}</style>`;
export const STYLE_PREFIX = `<style>(?:${JOINER}[a-z]+)*${JOINER}(?:</style>)?`;
