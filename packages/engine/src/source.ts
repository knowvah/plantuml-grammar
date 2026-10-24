// Port of tools/interp/source.py: turn a block's text into the line stream upstream's
// command loop sees.
//
// Mirrors, at 97a5992:
//
// * utils/StartUtils.java:51-63 (isStartDirective) and :95-121 (isEndDirective): a start
//   line is `\s*[@\\]start` plus at least one more character; the command loop stops at
//   the first line starting with `[@\\]end` (command/PSystemCommandFactory.java:129-132).
// * core/DiagramType.java:69-92: the diagram types come from the text after `start`.
// * preproc2/ReadFilterQuoteComment.java:45-80: `'` line comments and `/' ... '/` block
//   comments never reach the factories.
// * preproc/ReadLineReader.java:89-102: BufferedReader.readLine ends a line at `\n`, `\r`
//   or `\r\n`, a leading U+FEFF is dropped and U+2013 becomes `-`. Nothing else touches
//   the text (tabs and trailing blanks survive), so `Line.text` is what
//   SingleLineCommand2(doTrim=false) matches (SingleLineCommand2.java:76-81, :93, :102).
// * StringUtils.java:505-530 (trin): lines are trimmed of every char <= ' '.
// * EmbeddedDiagram.java:257-300 and :77-78: `{{` / `{{type` ... `}}` groups are glued
//   into one multiline unit (PSystemCommandFactory.java:288-307).
// * BlockUmlBuilder.java:100-135 (splitBlocks): a file splits into blocks; a start line
//   opens a block (discarding any unterminated one, :101-104), the first end line closes
//   it (:126-135), and text outside blocks is ignored (:113).
//
// Known gaps: @pause / @unpause / !exit (BlockUmlBuilder.java:105-125) are not modelled
// by splitBlocks, which also sees comments the preprocessor would remove.
// StringLocated.removeInnerComment (ReadFilterQuoteComment.java:76) strips inline
// `/' ... '/` from kept lines; it is not reproduced.
//
// JS `trim()` and `\s` differ from Python `str.strip()` / `isspace()` (they include
// U+FEFF and omit U+001C-U+001F and U+0085), so the Python sets are spelled out below.

export interface Line {
  /** 1-based number within the block text. */
  readonly number: number;
  readonly text: string;
  readonly trimmed: string;
}

export interface Block {
  readonly start: Line | null;
  readonly keyword: string | null;
  readonly body: Line[];
  readonly end: Line | null;
}

const LINE_BREAKS = /\r\n|\r|\n/;
const BYTE_ORDER_MARK = "﻿";
const EN_DASH = "–";
const HYPHEN = "-";
const TRIN_MAX = 0x20;
const START_WORD = "start";
const END_WORD = "end";
const DIRECTIVE_MARKS: ReadonlySet<string> = new Set(["@", "\\"]);
const LINE_COMMENT = "'";
const LONG_COMMENT_START = "/'";
const LONG_COMMENT_END = "'/";
const EMBEDDED_START = "{{";
const EMBEDDED_END = "}}";
const EMBEDDED_DEFAULT = "uml";
const TAB = "\t";
const SPACE = " ";
const CARRIAGE_RETURN = "\r";
const EMBEDDED_TYPES: ReadonlySet<string> = new Set(
  (
    "board creole chronology chen chart ditaa ebnf files gantt json mindmap nwdiag " +
    "packetdiag regex salt uml wbs wire yaml"
  ).split(" "),
);
const START_KEYWORD_CHARS: ReadonlySet<string> = new Set(
  "abcdefghijklmnopqrstuvwxyz0123456789_",
);

/** Every code point for which Python's `str.isspace()` (and so `strip()`) is true. */
const PY_WHITESPACE: ReadonlySet<number> = new Set([
  0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x85, 0xa0, 0x1680,
  0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009,
  0x200a, 0x2028, 0x2029, 0x202f, 0x205f, 0x3000,
]);

function isPySpace(unit: string): boolean {
  return PY_WHITESPACE.has(unit.codePointAt(0) ?? -1);
}

/** Strip leading/trailing chars for which `drop` holds (all such chars are BMP). */
function stripWhere(text: string, drop: (unit: string) => boolean): string {
  let from = 0;
  let to = text.length;
  while (from < to && drop(text.charAt(from))) from += 1;
  while (to > from && drop(text.charAt(to - 1))) to -= 1;
  return text.slice(from, to);
}

/** Python `str.rstrip()` with no argument. */
function pyRstrip(text: string): string {
  let to = text.length;
  while (to > 0 && isPySpace(text.charAt(to - 1))) to -= 1;
  return text.slice(0, to);
}

/** Python `str.strip()` with no argument. */
function pyStrip(text: string): string {
  return stripWhere(text, isPySpace);
}

/** The text of a line as `ReadLineReader.readLine` hands it to the command loop. */
export function readLine(raw: string): string {
  const unmarked = raw.startsWith(BYTE_ORDER_MARK) ? raw.slice(BYTE_ORDER_MARK.length) : raw;
  return unmarked.replaceAll(EN_DASH, HYPHEN);
}

/** Upstream `StringUtils.trin`: strip every leading/trailing char <= ' '. */
export function trin(text: string): string {
  return stripWhere(text, (unit) => (unit.codePointAt(0) ?? Infinity) <= TRIN_MAX);
}

/** Index just past `[@\]word` if `text` (after whitespace) starts with it. */
function directiveWord(text: string, word: string): number | null {
  let i = 0;
  while (i < text.length && isPySpace(text.charAt(i))) i += 1;
  if (i >= text.length || !DIRECTIVE_MARKS.has(text.charAt(i))) return null;
  const end = i + 1 + word.length;
  return text.slice(i + 1, end) === word ? end : null;
}

/** `StartUtils.isStartDirective` (StartUtils.java:51-63). */
export function isStartDirective(text: string): boolean {
  const end = directiveWord(text, START_WORD);
  return end !== null && end < text.length;
}

/** `StartUtils.isEndDirective` (StartUtils.java:119-121). */
export function isEndDirective(text: string): boolean {
  return directiveWord(text, END_WORD) !== null;
}

/** Lower-cased word after `@start` (`uml`, `mindmap`, ...); `""` if none. */
export function startKeyword(text: string): string {
  const end = directiveWord(text, START_WORD);
  if (end === null) return "";
  let keyword = "";
  for (const ch of text.slice(end).toLowerCase()) {
    if (!START_KEYWORD_CHARS.has(ch)) break;
    keyword += ch;
  }
  return keyword;
}

/** `EmbeddedDiagram.getEmbeddedType`: `{{` alone is `uml`, else a known type. */
export function embeddedType(text: string): string | null {
  const stripped = pyStrip(text);
  if (!stripped.startsWith(EMBEDDED_START)) return null;
  const suffix = pyRstrip(stripped.slice(EMBEDDED_START.length));
  if (suffix === "") return EMBEDDED_DEFAULT;
  return EMBEDDED_TYPES.has(suffix) ? suffix : null;
}

/** A trimmed line equal to `}}` (PSystemCommandFactory.java:298). */
export function isEmbeddedEnd(text: string): boolean {
  return pyStrip(text) === EMBEDDED_END;
}

/** Drop comment lines exactly like `ReadFilterQuoteComment.readLine` (:52-77). */
export function stripComments(lines: readonly Line[]): Line[] {
  const kept: Line[] = [];
  let inLong = false;
  for (const line of lines) {
    const trim = pyStrip(line.text.replaceAll(TAB, SPACE));
    if (inLong) {
      inLong = !trim.endsWith(LONG_COMMENT_END);
    } else if (trim.startsWith(LINE_COMMENT)) {
      continue;
    } else if (trim.startsWith(LONG_COMMENT_START)) {
      if (trim.endsWith(LONG_COMMENT_END)) continue;
      if (!trim.includes(LONG_COMMENT_END)) {
        inLong = true;
        continue;
      }
      kept.push(line);
    } else {
      kept.push(line);
    }
  }
  return kept;
}

/**
 * Split into start line, keyword and the lines the command loop iterates.
 *
 * A block without a leading `@start` line is treated as body only (the harness may hand
 * over bare bodies); `keyword` is then `null`.
 */
export function splitBlock(blockText: string): Block {
  const lines = blockText.split(LINE_BREAKS).map((raw, index): Line => {
    const text = readLine(raw);
    return { number: index + 1, text, trimmed: trin(text) };
  });
  const first = lines.findIndex((ln) => ln.trimmed !== "");
  const head = first === -1 ? undefined : lines[first];
  let start: Line | null = null;
  let keyword: string | null = null;
  let rest = lines;
  if (head !== undefined && isStartDirective(head.text)) {
    start = head;
    keyword = startKeyword(head.text);
    rest = lines.slice(first + 1);
  }
  const body: Line[] = [];
  for (const line of stripComments(rest)) {
    if (isEndDirective(line.text)) return { start, keyword, body, end: line };
    body.push(line);
  }
  return { start, keyword, body, end: null };
}

/** The `@start...@end` blocks of a file, as `BlockUmlBuilder` finds them. */
export function splitBlocks(text: string): string[] {
  const blocks: string[] = [];
  let current: string[] | null = null;
  for (const raw of text.split("\n")) {
    const line = rstripCarriageReturns(raw);
    if (isStartDirective(line)) current = [];
    if (current === null) continue;
    current.push(line);
    if (isEndDirective(line)) {
      blocks.push(current.join("\n"));
      current = null;
    }
  }
  return blocks;
}

/** Python `str.rstrip("\r")`. */
function rstripCarriageReturns(text: string): string {
  let to = text.length;
  while (to > 0 && text.charAt(to - 1) === CARRIAGE_RETURN) to -= 1;
  return text.slice(0, to);
}
