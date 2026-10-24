// Port of tools/interp/dispatch.py: choosing and ordering candidate diagram models
// for a block's start keyword. Upstream: PSystemBuilder.java:133-200, 258-284;
// core/DiagramType.java:69-232.
import type { EngineModelJson } from "./types.js";

export const DIAGRAM_LAYER = "diagram";
export const DOCUMENT_LAYER = "document";
export const START_PREFIX = "@start";

/** A model with its id; `plan` returns these in try-order. */
export interface ModelRef {
  readonly id: string;
  readonly model: EngineModelJson;
}

export type StartMap = Readonly<Record<string, readonly string[]>>;

export const UML_TYPES: ReadonlySet<string> = new Set(
  "SEQUENCE STATE CLASS OBJECT ACTIVITY DESCRIPTION COMPOSITE TIMING HELP SPRITES".split(" "),
);

const single = (type: string): ReadonlySet<string> => new Set([type]);

/** Keyword prefix -> DiagramTypes; iteration order is lookup priority. */
export const START_TYPES: ReadonlyMap<string, ReadonlySet<string>> = new Map([
  ["bpm", single("BPM")],
  ["board", single("BOARD")],
  ["chart", single("CHART")],
  ["creole", single("CREOLE")],
  ["chronology", single("CHRONOLOGY")],
  ["chen", single("CHEN_EER")],
  ["crash", single("CRASH")],
  ["dot", single("DOT")],
  ["ditaa", single("DITAA")],
  ["def", single("DEFINITION")],
  ["ebnf", single("EBNF")],
  ["flow", single("FLOW")],
  ["files", single("FILES")],
  ["gantt", single("GANTT")],
  ["project", single("GANTT")],
  ["git", single("GIT")],
  ["hcl", single("HCL")],
  ["jcckit", single("JCCKIT")],
  ["json", single("JSON")],
  ["latex", single("LATEX")],
  ["math", single("MATH")],
  ["mindmap", single("MINDMAP")],
  ["nwdiag", single("NWDIAG")],
  ["packetdiag", single("PACKET")],
  ["regex", single("REGEX")],
  ["salt", single("SALT")],
  ["sprites", single("SPRITES")],
  ["uml", UML_TYPES],
  ["wire", single("WIRE")],
  ["wbs", single("WBS")],
  ["yaml", single("YAML")],
]);

/** DiagramType of each factory in PSystemBuilder.java:133-200, first occurrence only. */
export const FACTORY_TYPE_ORDER: readonly string[] = (
  "SEQUENCE CLASS ACTIVITY DESCRIPTION STATE BPM SALT DOT NWDIAG MINDMAP WBS CHART " +
  "PACKET DITAA DEFINITION SPRITES MATH LATEX CREOLE GANTT FLOW TIMING HELP WIRE JSON " +
  "GIT FILES BOARD YAML HCL EBNF REGEX CHEN_EER CRASH"
).split(" ");

const ORDER_INDEX: ReadonlyMap<string, number> = new Map(
  FACTORY_TYPE_ORDER.map((name, n) => [name, n]),
);

/** `DiagramType.findStartTypes` as a prefix lookup; empty when unknown. */
export function startTypes(keyword: string): ReadonlySet<string> {
  for (const [prefix, types] of START_TYPES) {
    if (keyword.startsWith(prefix)) return types;
  }
  return new Set();
}

function own<T>(table: Readonly<Record<string, T>>, key: string): T | undefined {
  return Object.hasOwn(table, key) ? table[key] : undefined;
}

/** Names mapped to `keyword`: exact key, `@start` + key, then a prefix key. */
export function lookup(startMap: StartMap, keyword: string): readonly string[] | null {
  for (const key of [keyword, START_PREFIX + keyword]) {
    const names = own(startMap, key);
    if (names !== undefined) return names;
  }
  for (const [key, names] of Object.entries(startMap)) {
    const bare = key.startsWith(START_PREFIX) ? key.slice(START_PREFIX.length) : key;
    if (bare !== "" && keyword.startsWith(bare)) return names;
  }
  return null;
}

/** The `start_map` of the first document-layer model that has a non-empty one. */
export function documentStartMap(
  models: Readonly<Record<string, EngineModelJson>>,
  modelOrder: readonly string[],
): StartMap | null {
  for (const id of modelOrder) {
    const model = own(models, id);
    if (
      model !== undefined &&
      model.layer === DOCUMENT_LAYER &&
      Object.keys(model.start_map).length > 0
    ) {
      return model.start_map;
    }
  }
  return null;
}

/** Candidate diagram models per start keyword for one model set. */
export class Dispatcher {
  readonly #models: Readonly<Record<string, EngineModelJson>>;
  readonly #order: readonly string[];
  readonly #tops: Readonly<Record<string, string>>;
  readonly #map: StartMap | null;

  constructor(
    models: Readonly<Record<string, EngineModelJson>>,
    modelOrder: readonly string[],
    tops: Readonly<Record<string, string>>,
    startMap?: StartMap,
  ) {
    this.#models = models;
    this.#order = modelOrder;
    this.#tops = tops;
    this.#map = startMap ?? documentStartMap(models, modelOrder);
  }

  /** Models to try in order; `null` means PSystemUnsupported. `null` keyword: bare body. */
  plan(keyword: string | null): ModelRef[] | null {
    if (keyword === null) return this.#diagramModels();
    if (this.#map === null) return this.#byType(keyword);
    const names = lookup(this.#map, keyword);
    if (names === null) return null;
    const picked: ModelRef[] = [];
    for (const name of names) {
      const ref = this.#pick(name);
      if (ref !== null) picked.push(ref);
    }
    return picked;
  }

  #ref(id: string): ModelRef | null {
    const model = own(this.#models, id);
    return model === undefined ? null : { id, model };
  }

  #pick(name: string): ModelRef | null {
    const top = own(this.#tops, name);
    if (top !== undefined) return this.#ref(top);
    const ref = this.#ref(name);
    return ref !== null && ref.model.layer === DIAGRAM_LAYER ? ref : null;
  }

  #diagramModels(): ModelRef[] {
    const out: ModelRef[] = [];
    for (const id of this.#order) {
      const ref = this.#ref(id);
      if (ref !== null && ref.model.layer === DIAGRAM_LAYER) out.push(ref);
    }
    return out;
  }

  #byType(keyword: string): ModelRef[] | null {
    const types = startTypes(keyword);
    if (types.size === 0) return null;
    const rank = (ref: ModelRef): number =>
      ORDER_INDEX.get(ref.model.diagram ?? "") ?? ORDER_INDEX.size;
    return this.#diagramModels()
      .filter((ref) => ref.model.diagram !== null && types.has(ref.model.diagram))
      .sort((a, b) => rank(a) - rank(b));
  }
}
