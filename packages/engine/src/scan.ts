// Port of tools/interp/scan.py: multiline end detection.
//
// Mirrors `command/PSystemCommandFactory.java:268-286` (`isMultilineCommandOk`): lines
// are appended one unit at a time (`:288-307` glues `{{ ... }}` embedded diagrams into
// one unit), the command is re-validated after each unit, and `NOT_OK` / running out of
// lines drops the candidate so the next command is tried.
//
// * `multiline`: `command/CommandMultilines2.java:79-110` (and
//   `CommandMultilines.java:58-74`): one line is always `OK_PARTIAL`; with more lines,
//   `OK` iff the last line, trimmed, fully matches the `end` pattern. Only the last
//   line is tested, so cost is one regex per appended line.
// * `multiline-bracket`: `command/CommandMultilinesBracket.java:64-96`: bracket depth
//   starts at 1; each later trimmed line ending in `{` adds one, ending in `}` removes
//   one; below 0 is `NOT_OK`; `OK` when depth returns to 0. Depth is maintained
//   incrementally (same result, linear time).
// * `multiline` + `join`: `command/CommandDecoratorMultine.java:77-93` with the cap at
//   `PSystemCommandFactory.java:281`: units 1..k (k <= max_lines + 1) are joined with
//   U+E100 (`utils/BlocLines.java:296`) and must fully match `parts`; the smallest k
//   wins, k = 1 is the single-line case, and no match within the cap drops the command.
//
// Factories that are not `PSystemCommandFactory` subclasses (`PSystemAbstractFactory`
// readers such as `JsonDiagramFactory` / `FilesDiagramFactory`, which take plain lines
// from `jsondiagram/StyleExtractor.java:63-103`) do not glue `{{ ... }}`: the scanners
// take `glue = false` for their rules.
//
// Divergence from Python (decision D4): the early stop tests the entry's `join.prefix`
// pattern against `joined + JOINER` instead of regex partial matching.
//
// Known gaps (not representable in the model): `isLineConsistent` (abstract, per
// command), `finalVerification` hooks, and the `MultilinesStrategy.REMOVE_STARTING_QUOTE`
// line filter (`MultilinesStrategy.java`; `'` lines are already gone, see `source`).
import type { Deadline } from "./deadline.js";
import type { Matcher } from "./matcher.js";
import { embeddedType, isEmbeddedEnd } from "./source.js";
import type { Line } from "./source.js";

export const BRACKET_OPEN = "{";
export const BRACKET_CLOSE = "}";
export const JOINER = "\ue100";

/** A `join` rule: the whole-line start pattern, the optional prefix pattern, the cap. */
export interface Join {
  readonly start: Matcher;
  /** Pattern that fails once no extension of the joined text can match; null = never stops. */
  readonly prefix: Matcher | null;
  readonly maxLines: number;
  readonly glueUnits: boolean;
}

const textAt = (body: readonly Line[], k: number): string => body[k]?.text ?? "";

/** End (exclusive) of the unit starting at `j` (`PSystemCommandFactory.java:288`). */
export function unitEnd(body: readonly Line[], j: number, glue = true): number {
  if (!glue || embeddedType(textAt(body, j)) === null) return j + 1;
  let nested = 1;
  for (let k = j + 1; k < body.length; k += 1) {
    const text = textAt(body, k);
    if (embeddedType(text) !== null) {
      nested += 1;
    } else if (isEmbeddedEnd(text)) {
      nested -= 1;
      if (nested === 0) return k + 1;
    }
  }
  return body.length;
}

/** Index after a `multiline` command starting at `i`, or null (dropped). */
export function scanMultiline(
  end: Matcher,
  body: readonly Line[],
  i: number,
  deadline: Deadline,
  glue = true,
): number | null {
  let j = i;
  while (j < body.length) {
    j = unitEnd(body, j, glue);
    if (j - i > 1 && end.test(body[j - 1]?.trimmed ?? "", deadline)) return j;
  }
  return null;
}

/** Index after a `multiline-bracket` command starting at `i`, or null. */
export function scanBracket(body: readonly Line[], i: number, glue = true): number | null {
  let level = 1;
  let j = i;
  while (j < body.length) {
    const next = unitEnd(body, j, glue);
    for (let k = Math.max(j, i + 1); k < next; k += 1) {
      const text = body[k]?.trimmed ?? "";
      level += Number(text.endsWith(BRACKET_OPEN)) - Number(text.endsWith(BRACKET_CLOSE));
      if (level < 0) return null;
    }
    j = next;
    if (j - i > 1 && level === 0) return j;
  }
  return null;
}

/**
 * Whether `prefix` rules out every extension of `text`; null when it cannot tell.
 *
 * V8 throws `RangeError` when a regex runs out of backtracking stack, where Python's
 * `regex` partial match still answers. The prefix only cuts the scan short, so not
 * knowing means keep scanning: the full `start` test still decides every k.
 */
function prefixRejects(prefix: Matcher, text: string, deadline: Deadline): boolean | null {
  try {
    return !prefix.test(text, deadline);
  } catch (error) {
    if (error instanceof RangeError) return null;
    throw error;
  }
}

/** Index after a `join` command starting at `i`, or null (dropped). */
export function scanJoin(
  join: Join,
  body: readonly Line[],
  i: number,
  deadline: Deadline,
): number | null {
  let prefix = join.prefix;
  let j = i;
  for (let n = 0; n <= join.maxLines; n += 1) {
    if (j >= body.length) return null;
    j = unitEnd(body, j, join.glueUnits);
    const joined = body
      .slice(i, j)
      .map((line) => line.trimmed)
      .join(JOINER);
    if (join.start.test(joined, deadline)) return j;
    if (prefix === null) continue;
    // No extension of joined + JOINER can match, so no larger k can: stop early.
    const rejects = prefixRejects(prefix, joined + JOINER, deadline);
    if (rejects === true) return null;
    // Longer joined text only overflows deeper: stop trying the prefix.
    if (rejects === null) prefix = null;
  }
  return null;
}
