// Native recognizer for the well-formed `@startregex` line (`RX_WELL_FORMED` in
// model/diagrams/meta-diagrams-regex.yaml, the start pattern of RegexLineWellFormed).
// The leaf is a recursive `(?(DEFINE)...)` grammar; its bounded JavaScript expansion was a
// 465 KB regex that cost about a second to compile on first use (#4).
//
// Browser-safe and import-free so that Node can run it directly with type stripping.
// tests/model/test_native_regex.py checks it against the Python `regex` fullmatch of the
// leaf translated by tools/model/java_regex.py, whose semantics are reproduced here:
// `.` refuses `\n \r \x85 U+2028 U+2029`, `\Z` allows one final line terminator, and
// `[^...]` classes match any other code point, line terminators included.
//
// Every repetition in the grammar is possessive and every alternation is decided by its
// first character, so a greedy recursive-descent parse without backtracking is exact.
// Each function takes a position and returns the position after what it consumed, or NO.

const NO = -1;
const NUL = 0x00;
const LF = 0x0a;
const CR = 0x0d;
const NEL = 0x85;
const LINE_SEPARATOR = 0x2028;
const PARAGRAPH_SEPARATOR = 0x2029;
const BANG = 0x21;
const HASH = 0x23;
const DOLLAR = 0x24;
const LPAREN = 0x28;
const RPAREN = 0x29;
const STAR = 0x2a;
const PLUS = 0x2b;
const COMMA = 0x2c;
const DOT = 0x2e;
const ZERO = 0x30;
const NINE = 0x39;
const COLON = 0x3a;
const LT = 0x3c;
const EQUALS = 0x3d;
const GT = 0x3e;
const QUESTION = 0x3f;
const LBRACKET = 0x5b;
const BACKSLASH = 0x5c;
const RBRACKET = 0x5d;
const CARET = 0x5e;
const LOWER_P = 0x70;
const LOWER_U = 0x75;
const LOWER_X = 0x78;
const LBRACE = 0x7b;
const PIPE = 0x7c;
const RBRACE = 0x7d;
const BMP_MAX = 0xffff;
/** Characters an operand never starts with (besides those with their own rule). */
const OPERATORS = [NUL, LPAREN, RPAREN, STAR, PLUS, QUESTION, LBRACE, PIPE];
const OCTAL_ESCAPE_CHARS = 3;
const UNICODE_ESCAPE_CHARS = 4;
const POSIX_TAIL_CHARS = 2;
const LETTER = /\p{L}/u;

/** Code point at `p`, or NO at the end. */
function cp(s: string, p: number): number {
  return p < s.length ? (s.codePointAt(p) as number) : NO;
}

function width(c: number): number {
  return c > BMP_MAX ? 2 : 1;
}

function isDigit(c: number): boolean {
  return c >= ZERO && c <= NINE;
}

/** The characters Java's `.` refuses. */
function isLineTerminator(c: number): boolean {
  return c === LF || c === CR || c === NEL || c === LINE_SEPARATOR || c === PARAGRAPH_SEPARATOR;
}

/** The translated `\Z`: the end of the string, with at most one line terminator before it. */
function lineEndsAt(s: string, p: number): boolean {
  if (p === s.length) return true;
  const c = s.charCodeAt(p);
  if (c === CR && s.charCodeAt(p + 1) === LF) return p + 2 === s.length;
  if (c === LF && s.charCodeAt(p - 1) === CR) return false;
  return isLineTerminator(c) && p + 1 === s.length;
}

/** `(?:\(\?#[^)\x00]*\))*+`: comments, as many as are closed. */
function comments(s: string, p: number): number {
  let q = p;
  while (s.startsWith("(?#", q)) {
    let r = q + 3;
    while (r < s.length && s.charCodeAt(r) !== RPAREN && s.charCodeAt(r) !== NUL) r += 1;
    if (s.charCodeAt(r) !== RPAREN) return q;
    q = r + 1;
  }
  return q;
}

/** `count` code points that are not line terminators, from `q`. */
function fixedChars(s: string, q: number, count: number): number {
  let r = q;
  for (let k = 0; k < count; k += 1) {
    const c = cp(s, r);
    if (c === NO || isLineTerminator(c)) return NO;
    r += width(c);
  }
  return r;
}

/** `\0` + 3 chars, `\u` + 4 chars, `\p{...}` / `\x{...}`, or `\` + one char. */
function escape(s: string, p: number): number {
  const c = cp(s, p + 1);
  if (c === NO) return NO;
  if (c === ZERO) return fixedChars(s, p + 2, OCTAL_ESCAPE_CHARS);
  if (c === LOWER_U) return fixedChars(s, p + 2, UNICODE_ESCAPE_CHARS);
  if ((c === LOWER_P || c === LOWER_X) && s.charCodeAt(p + 2) === LBRACE) {
    const close = s.indexOf("}", p + 3);
    return close === NO ? NO : close + 1;
  }
  return isLineTerminator(c) ? NO : p + 1 + width(c);
}

/** `\[\[:[^:]*:..`, from the `[[:`. */
function posix(s: string, p: number): number {
  const colon = s.indexOf(":", p + 3);
  return colon === NO ? NO : fixedChars(s, colon + 1, POSIX_TAIL_CHARS);
}

/** `(?:[^\]\\\x00]|\\.)+` from `q`, greedily: the end, which is `q` when nothing matched. */
function classUnits(s: string, q: number): number {
  let r = q;
  for (;;) {
    const c = cp(s, r);
    if (c === NO || c === RBRACKET || c === NUL) return r;
    if (c !== BACKSLASH) {
      r += width(c);
      continue;
    }
    const d = cp(s, r + 1);
    if (d === NO || isLineTerminator(d)) return r;
    r += 1 + width(d);
  }
}

/** `\[(?!\[:)(?:[^\]\\\x00]|\\.)+(?:\]|\Z|(?=\x00))`, from the `[`. */
function charClass(s: string, p: number): number {
  const q = classUnits(s, p + 1);
  if (q === p + 1) return NO;
  if (s.charCodeAt(q) === RBRACKET) return q + 1;
  return s.charCodeAt(q) === NUL || lineEndsAt(s, q) ? q : NO;
}

/** `rxo`: one operand, then comments. */
function operand(s: string, p: number): number {
  const c = cp(s, p);
  if (c === NO || OPERATORS.includes(c)) return NO;
  let end: number;
  if (c === BACKSLASH) end = escape(s, p);
  else if (c === LBRACKET) end = s.startsWith("[[:", p) ? posix(s, p) : charClass(s, p);
  else if (c === CARET || c === DOLLAR || c === DOT) end = p + 1;
  else end = p + width(c);
  return end === NO ? NO : comments(s, end);
}

/** `\{[0-9,]+\}(?!\?)`, from the `{`. */
function bracedQuantifier(s: string, p: number): number {
  let q = p + 1;
  while (isDigit(s.charCodeAt(q)) || s.charCodeAt(q) === COMMA) q += 1;
  if (q === p + 1 || s.charCodeAt(q) !== RBRACE || s.charCodeAt(q + 1) === QUESTION) return NO;
  return q + 1;
}

/** `rxq`: `[*+?]` with an optional `?`, or a braced quantifier; then comments. */
function quantifier(s: string, p: number): number {
  const c = cp(s, p);
  let end: number;
  if (c === STAR || c === PLUS || c === QUESTION) {
    end = s.charCodeAt(p + 1) === QUESTION ? p + 2 : p + 1;
  } else {
    end = c === LBRACE ? bracedQuantifier(s, p) : NO;
  }
  return end === NO ? NO : comments(s, end);
}

/** `(?<name>`: letters of the BMP only; the end after `>`, or NO. From the char after `<`. */
function namedGroup(s: string, p: number): number {
  let q = p;
  for (let c = cp(s, q); c !== NO && c <= BMP_MAX && LETTER.test(String.fromCodePoint(c)); ) {
    q += 1;
    c = cp(s, q);
  }
  return q > p && s.charCodeAt(q) === GT ? q + 1 : NO;
}

/** `rxlo`: `(?=` `(?!` `(?<=` `(?<!` or `(?<name>`, from the char after `(?`; else NO. */
function lookaroundOrNamed(s: string, p: number): number {
  const c = s.charCodeAt(p);
  if (c === EQUALS || c === BANG) return p + 1;
  if (c !== LT) return NO;
  const d = s.charCodeAt(p + 1);
  if (d === EQUALS || d === BANG) return p + 2;
  return namedGroup(s, p + 1);
}

/** `rxpo`: `(` with an optional `?:` and then an optional `?!`, from the `(`. */
function plainGroup(s: string, p: number): number {
  let q = p + 1;
  if (s.charCodeAt(q) === QUESTION && s.charCodeAt(q + 1) === COLON) q += 2;
  if (s.charCodeAt(q) === QUESTION && s.charCodeAt(q + 1) === BANG) q += 2;
  return q;
}

/** The end of the group opener at `(`, then comments; NO when `(?#` starts a comment. */
function groupOpen(s: string, p: number): number {
  if (s.charCodeAt(p + 1) !== QUESTION) return comments(s, p + 1);
  if (s.charCodeAt(p + 2) === HASH) return NO;
  const special = lookaroundOrNamed(s, p + 2);
  return comments(s, special === NO ? plainGroup(s, p) : special);
}

function quantifiers(s: string, q: number): number {
  let r = q;
  for (let e = quantifier(s, r); e !== NO; e = quantifier(s, r)) r = e;
  return r;
}

/**
 * `rxalt`, parsed with an explicit stack so nesting depth is unbounded. `lastGood` holds,
 * per open group (index 0 is the line itself), what the group's alternation ends at if the
 * next atom fails: NO before its first atom, else the end of the last atom and its
 * quantifiers (also the position of a `|` whose branch then fails, since the repetition
 * is possessive). A group that does not close fails everything up to the line's own value.
 */
function alternationEnd(s: string, i: number): number {
  const lastGood = [NO];
  let q = comments(s, i);
  for (;;) {
    const group = cp(s, q) === LPAREN;
    const end = group ? groupOpen(s, q) : operand(s, q);
    if (end !== NO) {
      q = group ? openGroup(lastGood, end) : settleAtom(s, end, lastGood);
      continue;
    }
    const good = lastGood[lastGood.length - 1] as number;
    if (good === NO) return lastGood[0] as number;
    if (q === good && s.charCodeAt(q) === PIPE) {
      q = comments(s, q + 1);
      continue;
    }
    if (lastGood.length === 1) return good;
    q = closeGroup(s, good, lastGood);
    if (q === NO) return lastGood[0] as number;
  }
}

/** A group opened: its first sequence has no atom yet. */
function openGroup(lastGood: number[], afterOpener: number): number {
  lastGood.push(NO);
  return afterOpener;
}

/** An operand matched up to `end`: take its quantifiers and record the sequence's end. */
function settleAtom(s: string, end: number, lastGood: number[]): number {
  const q = quantifiers(s, end);
  lastGood[lastGood.length - 1] = q;
  return q;
}

/** A group's alternation ended at `good`: past `)`, comments and quantifiers, or NO. */
function closeGroup(s: string, good: number, lastGood: number[]): number {
  if (s.charCodeAt(good) !== RPAREN) return NO;
  lastGood.pop();
  return settleAtom(s, comments(s, good + 1), lastGood);
}

/**
 * Ends of `RX_WELL_FORMED` matches starting at `i`: the one end of the greedy parse, after
 * a NUL and the rest of the line when a NUL follows the expression; empty when the line
 * is not well formed.
 */
export function regexWellFormedEnds(s: string, i: number): number[] {
  const end = alternationEnd(s, i);
  if (end === NO) return [];
  if (s.charCodeAt(end) !== NUL) return [end];
  let q = end + 1;
  while (q < s.length && !isLineTerminator(s.charCodeAt(q))) q += 1;
  return [q];
}
