// Port of tools/interp/rules.py: compiled rules of a model, built lazily per context.
//
// `untrimmed` (`trim: false`) mirrors `SingleLineCommand2(doTrim=false)`: the pattern is
// matched against `Line.text`, the line as the command loop receives it
// (`SingleLineCommand2.java:76-81` `myTrim2` returns the `StringLocated` untouched,
// `:93` and `:102` match it), instead of `Line.trimmed` (`getTrimmed`, `trin`).
//
// Patterns are whole-line in the engine JSON (C1), so no anchors are added here.
// A join without a `prefix` pattern never stops early (correct but slow).
import type { Deadline } from "./deadline.js";
import { UnknownContextError } from "./load.js";
import type { EngineModel } from "./load.js";
import { scanBracket, scanJoin, scanMultiline } from "./scan.js";
import type { Join } from "./scan.js";
import type { Matcher } from "./matcher.js";
import type { Line } from "./source.js";
import type { EngineModelJson, EntryJson } from "./types.js";

export const KIND_SINGLE = "single";
export const KIND_MULTILINE = "multiline";
export const KIND_BRACKET = "multiline-bracket";
export const KIND_OPAQUE = "opaque";
export const ACTION_PUSH = "push";
export const ACTION_POP = "pop";
export const ACTION_SET = "set";
export const ACTION_NONE = "";

export type RuleKind = EntryJson["kind"];
export type RuleAction = EntryJson["action"];

export interface RuleFields {
  readonly name: string;
  readonly kind: RuleKind;
  readonly start: Matcher;
  readonly end: Matcher | null;
  readonly join: Join | null;
  readonly action: RuleAction;
  readonly target: string;
  readonly requirePop: boolean;
  readonly reject: boolean;
  readonly gives: string;
  readonly needs: string;
  readonly untrimmed: boolean;
  readonly glueUnits: boolean;
}

/** One command with its compiled patterns and context transition. */
export class Rule implements RuleFields {
  readonly name: string;
  readonly kind: RuleKind;
  readonly start: Matcher;
  readonly end: Matcher | null;
  readonly join: Join | null;
  readonly action: RuleAction;
  readonly target: string;
  readonly requirePop: boolean;
  readonly reject: boolean;
  readonly gives: string;
  readonly needs: string;
  readonly untrimmed: boolean;
  readonly glueUnits: boolean;

  constructor(f: RuleFields) {
    this.name = f.name;
    this.kind = f.kind;
    this.start = f.start;
    this.end = f.end;
    this.join = f.join;
    this.action = f.action;
    this.target = f.target;
    this.requirePop = f.requirePop;
    this.reject = f.reject;
    this.gives = f.gives;
    this.needs = f.needs;
    this.untrimmed = f.untrimmed;
    this.glueUnits = f.glueUnits;
  }

  /** Index after this command starting at `i`; null = no match or dropped. */
  advance(body: readonly Line[], i: number, deadline: Deadline): number | null {
    if (this.join !== null) return scanJoin(this.join, body, i, deadline);
    const first = body[i];
    if (first === undefined) return null;
    const line = this.untrimmed ? first.text : first.trimmed;
    if (!this.start.test(line, deadline)) return null;
    switch (this.kind) {
      case KIND_OPAQUE:
        return body.length;
      case KIND_MULTILINE:
        return this.end === null
          ? null
          : scanMultiline(this.end, body, i, deadline, this.glueUnits);
      case KIND_BRACKET:
        return scanBracket(body, i, this.glueUnits);
      default:
        return i + 1;
    }
  }
}

/** Compile a resolved command entry; `glue_units` comes from the model record. */
export function buildRule(entry: EntryJson, model: EngineModelJson, engine: EngineModel): Rule {
  const start = engine.matcher(entry.start);
  const glueUnits = model.glue_units;
  const join: Join | null =
    entry.join === undefined
      ? null
      : {
          start,
          prefix: entry.join.prefix === undefined ? null : engine.matcher(entry.join.prefix),
          maxLines: entry.join.max_lines,
          glueUnits,
        };
  return new Rule({
    name: entry.command,
    kind: entry.kind,
    start,
    end: entry.end === undefined ? null : engine.matcher(entry.end),
    join,
    action: entry.action,
    target: entry.target,
    requirePop: entry.require_pop,
    reject: entry.reject,
    gives: entry.gives,
    needs: entry.needs,
    untrimmed: entry.untrimmed,
    glueUnits,
  });
}

const KEY_SEPARATOR = "\0";

/** Lazily compiled `(model, context) -> Rule[]` for one engine (read-only). */
export class RuleBook {
  readonly #engine: EngineModel;
  readonly #cache = new Map<string, readonly Rule[]>();

  constructor(engine: EngineModel) {
    this.#engine = engine;
  }

  /** Rules of `context`; throws `UnknownContextError` if the model or context is missing. */
  rules(modelId: string, context: string): readonly Rule[] {
    const key = `${modelId}${KEY_SEPARATOR}${context}`;
    const cached = this.#cache.get(key);
    if (cached !== undefined) return cached;
    const model = this.#engine.models.get(modelId);
    if (model === undefined) throw new UnknownContextError(modelId, context);
    const built = this.#engine
      .context(modelId, context)
      .map((entry) => buildRule(entry, model, this.#engine));
    this.#cache.set(key, built);
    return built;
  }
}
