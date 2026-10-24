// Native recognizers for the two recursive JSON leaves that JavaScript regexes cannot
// express (decision D3a, contract C8). Ports the language of `CO_JSON_BLOCK_BODY` and
// `CO_JSON_DATA_INVALID` in model/diagrams/class-objects.yaml:45-56, matched by
// `regex.fullmatch(to_python(leaf), s)` in tests/model/test_native_json.py.
//
// Browser-safe and import-free so that Node can run it directly with type stripping.
// Parsing is iterative (an explicit stack), so nesting depth is unbounded and the block
// body is recognised in time linear in the input.
//
// The grammar is not standard JSON: U+E100 (the joiner of concatenated lines) is
// whitespace and may appear inside numbers and literals; the string escapes are exactly
// `["\\/bfnrt]` and `u` + 4 hex digits; whitespace is `[ \t\n\r]` plus U+E100.
//
// Java semantics reproduced for `CO_JSON_DATA_INVALID`: `.` refuses `\n \r \x85
// U+2028 U+2029`; `\d` and `\s` are ASCII; case folding is ASCII only.
//
// Deterministic structure used throughout: strings, literals, arrays and objects have at
// most one end. Only numbers have several (every digit prefix). Inside a container only
// the longest number end can be followed by `,` `]` `}` `:` or whitespace, so nested
// values use the longest end; the root value reports every end.

const NO = -1;
const JOINER = 0xe100;
const QUOTE = 0x22;
const BACKSLASH = 0x5c;
const COMMA = 0x2c;
const COLON = 0x3a;
const MINUS = 0x2d;
const PLUS = 0x2b;
const DOT = 0x2e;
const LBRACKET = 0x5b;
const RBRACKET = 0x5d;
const LBRACE = 0x7b;
const RBRACE = 0x7d;
const NBSP = 0xa0;
const NEL = 0x85;
const LINE_SEPARATOR = 0x2028;
const PARAGRAPH_SEPARATOR = 0x2029;
const ZERO = 0x30;
const NINE = 0x39;
const ASCII_CASE_BIT = 0x20;
const FIRST_PRINTABLE = 0x20;
const UNICODE_ESCAPE_DIGITS = 4;
const SIMPLE_ESCAPES = '"\\/bfnrt';
const UNICODE_ESCAPE = 0x75;
const LITERALS = ["true", "false", "null"] as const;
/** Opening and closing quotes of an object key in the data-invalid forms. */
const KEY_QUOTES = [QUOTE, 0x201c, 0x201d, 0xe121];

const WANT_VALUE = 0;
const WANT_KEY = 1;
const WANT_AFTER = 2;

function isDigit(c: number): boolean {
  return c >= ZERO && c <= NINE;
}

function isHex(c: number): boolean {
  return isDigit(c) || (c >= 0x41 && c <= 0x46) || (c >= 0x61 && c <= 0x66);
}

function isJsonSpace(c: number): boolean {
  return c === 0x20 || c === 0x09 || c === 0x0a || c === 0x0d || c === JOINER;
}

/** Java `\s` (ASCII) plus U+00A0, as in `[\s\xa0]`. */
function isDataSpace(c: number): boolean {
  return c === 0x20 || (c >= 0x09 && c <= 0x0d) || c === NBSP;
}

/** The characters Java's `.` refuses. */
function isLineTerminator(c: number): boolean {
  return (
    c === 0x0a || c === 0x0d || c === NEL || c === LINE_SEPARATOR || c === PARAGRAPH_SEPARATOR
  );
}

function skipWhile(s: string, p: number, test: (c: number) => boolean): number {
  let q = p;
  while (test(s.charCodeAt(q))) q += 1;
  return q;
}

const skipWs = (s: string, p: number): number => skipWhile(s, p, isJsonSpace);
const skipJoiner = (s: string, p: number): number => skipWhile(s, p, (c) => c === JOINER);

/** Length of the escape body after a backslash (0 = invalid). */
function escapeLength(s: string, q: number): number {
  const c = s.charCodeAt(q);
  if (c === UNICODE_ESCAPE) {
    for (let k = 1; k <= UNICODE_ESCAPE_DIGITS; k += 1) {
      if (!isHex(s.charCodeAt(q + k))) return 0;
    }
    return UNICODE_ESCAPE_DIGITS + 1;
  }
  return SIMPLE_ESCAPES.includes(s.charAt(q)) && q < s.length ? 1 : 0;
}

/** End of the JSON string starting at `i` (`jstr`), or NO. */
function stringEnd(s: string, i: number): number {
  let p = i + 1;
  for (;;) {
    const c = s.charCodeAt(p);
    if (c === QUOTE) return p + 1;
    if (!(c >= FIRST_PRINTABLE)) return NO;
    if (c === BACKSLASH) {
      const n = escapeLength(s, p + 1);
      if (n === 0) return NO;
      p += 1 + n;
    } else {
      p += 1;
    }
  }
}

/** End of `t*r*u*e` style literals, or NO. */
function literalEnd(s: string, i: number, word: string): number {
  let p = i;
  for (let k = 0; k < word.length; k += 1) {
    if (k > 0) p = skipJoiner(s, p);
    if (s.charCodeAt(p) !== word.charCodeAt(k)) return NO;
    p += 1;
  }
  return p;
}

/** Pushes the end after each digit of `[0-9](*[0-9])*` starting at digit `p`. */
function digitEnds(s: string, p: number, out: number[]): void {
  let end = p + 1;
  out.push(end);
  for (;;) {
    const r = skipJoiner(s, end);
    if (!isDigit(s.charCodeAt(r))) return;
    end = r + 1;
    out.push(end);
  }
}

function intEnds(s: string, p: number, out: number[]): void {
  const c = s.charCodeAt(p);
  if (c === ZERO) out.push(p + 1);
  else if (isDigit(c)) digitEnds(s, p, out);
}

function fracEnds(s: string, e: number, out: number[]): void {
  let r = skipJoiner(s, e);
  if (s.charCodeAt(r) !== DOT) return;
  r = skipJoiner(s, r + 1);
  if (isDigit(s.charCodeAt(r))) digitEnds(s, r, out);
}

function expEnds(s: string, e: number, out: number[]): void {
  let r = skipJoiner(s, e);
  if ((s.charCodeAt(r) | ASCII_CASE_BIT) !== 0x65) return;
  r = skipJoiner(s, r + 1);
  const sign = s.charCodeAt(r);
  if (sign === PLUS || sign === MINUS) r += 1;
  r = skipJoiner(s, r);
  if (isDigit(s.charCodeAt(r))) digitEnds(s, r, out);
}

/** Every end of the number at `i`: `-?*(0|[1-9]…)(frac)?(exp)?`; unsorted. */
function numberEnds(s: string, i: number): number[] {
  const start = skipJoiner(s, s.charCodeAt(i) === MINUS ? i + 1 : i);
  const ints: number[] = [];
  intEnds(s, start, ints);
  const withFrac = [...ints];
  for (const e of ints) fracEnds(s, e, withFrac);
  const all = [...withFrac];
  for (const e of withFrac) expEnds(s, e, all);
  return all;
}

function maxOf(values: readonly number[]): number {
  return values.reduce((a, b) => Math.max(a, b), NO);
}

function startsNumber(c: number): boolean {
  return c === MINUS || c === JOINER || isDigit(c);
}

function scalarEnd(s: string, p: number): number {
  const c = s.charCodeAt(p);
  if (c === QUOTE) return stringEnd(s, p);
  if (startsNumber(c)) return maxOf(numberEnds(s, p));
  for (const word of LITERALS) {
    if (c === word.charCodeAt(0)) return literalEnd(s, p, word);
  }
  return NO;
}

/** Iterative `jv` parser; yields the single (longest) end of a value. */
class ValueParser {
  p: number;
  want = WANT_VALUE;
  readonly stack: number[] = [];
  readonly s: string;

  constructor(s: string, i: number) {
    this.s = s;
    this.p = i;
  }

  run(): number {
    while (this.p !== NO) {
      if (this.want === WANT_AFTER && this.stack.length === 0) return this.p;
      if (this.want === WANT_VALUE) this.value();
      else if (this.want === WANT_KEY) this.key();
      else this.after();
    }
    return NO;
  }

  finish(end: number): void {
    this.p = end;
    this.want = WANT_AFTER;
  }

  open(opener: number, closer: number, want: number): void {
    this.p = skipWs(this.s, this.p + 1);
    if (this.s.charCodeAt(this.p) === closer) this.finish(this.p + 1);
    else {
      this.stack.push(opener);
      this.want = want;
    }
  }

  value(): void {
    const c = this.s.charCodeAt(this.p);
    if (c === LBRACKET) this.open(LBRACKET, RBRACKET, WANT_VALUE);
    else if (c === LBRACE) this.open(LBRACE, RBRACE, WANT_KEY);
    else this.finish(scalarEnd(this.s, this.p));
  }

  key(): void {
    if (this.s.charCodeAt(this.p) !== QUOTE) {
      this.p = NO;
      return;
    }
    const e = stringEnd(this.s, this.p);
    const colon = e === NO ? NO : skipWs(this.s, e);
    if (colon === NO || this.s.charCodeAt(colon) !== COLON) {
      this.p = NO;
      return;
    }
    this.p = skipWs(this.s, colon + 1);
    this.want = WANT_VALUE;
  }

  after(): void {
    this.p = skipWs(this.s, this.p);
    const c = this.s.charCodeAt(this.p);
    const inArray = this.stack[this.stack.length - 1] === LBRACKET;
    if (c === COMMA) {
      this.p = skipWs(this.s, this.p + 1);
      this.want = inArray ? WANT_VALUE : WANT_KEY;
    } else if (c === (inArray ? RBRACKET : RBRACE)) {
      this.stack.pop();
      this.p += 1;
    } else {
      this.p = NO;
    }
  }
}

/** End of the `jv` value at `i` (longest for numbers), or NO. */
function valueEnd(s: string, i: number): number {
  return new ValueParser(s, i).run();
}

/** Every end of the root `jv` at `i`. */
function rootValueEnds(s: string, i: number): number[] {
  if (startsNumber(s.charCodeAt(i))) return numberEnds(s, i);
  const e = valueEnd(s, i);
  return e === NO ? [] : [e];
}

function pushRange(out: number[], from: number, to: number): void {
  for (let k = from; k <= to; k += 1) out.push(k);
}

function sortedUnique(values: readonly number[]): number[] {
  return [...new Set(values)].sort((a, b) => a - b);
}

/** Ends of `jmembers` at `p`: after each pair's value plus its trailing whitespace. */
function membersEnds(s: string, p: number, out: number[]): void {
  let q = p;
  for (;;) {
    if (s.charCodeAt(q) !== QUOTE) return;
    const keyEnd = stringEnd(s, q);
    const colon = keyEnd === NO ? NO : skipWs(s, keyEnd);
    if (colon === NO || s.charCodeAt(colon) !== COLON) return;
    const values = rootValueEnds(s, skipWs(s, colon + 1));
    if (values.length === 0) return;
    for (const e of values) pushRange(out, e, skipWs(s, e));
    q = skipWs(s, maxOf(values));
    if (s.charCodeAt(q) !== COMMA) return;
    q = skipWs(s, q + 1);
  }
}

/** Every `j` where `CO_JSON_BLOCK_BODY` can match `s` from `i` to `j`. */
export function jsonBlockBodyEnds(s: string, i: number): number[] {
  const out: number[] = [];
  const p = skipWs(s, i);
  pushRange(out, i, p);
  membersEnds(s, p, out);
  for (const e of rootValueEnds(s, p)) pushRange(out, e, skipWs(s, e));
  return sortedUnique(out);
}

// --- CO_JSON_DATA_INVALID ------------------------------------------------------------

function atEndOrTerminator(s: string, e: number): boolean {
  return e === s.length || isLineTerminator(s.charCodeAt(e));
}

/** ASCII-case-insensitive match of `word` at `i`. */
function matchesAsciiFolded(s: string, i: number, word: string): boolean {
  for (let k = 0; k < word.length; k += 1) {
    const c = s.charCodeAt(i + k);
    const lower = c >= 0x41 && c <= 0x5a ? c | ASCII_CASE_BIT : c;
    if (lower !== word.charCodeAt(k)) return false;
  }
  return true;
}

/** End of `-?(?:0|[1-9][0-9]*)` (greedy; shorter ends are followed by a digit), or NO. */
function plainIntegerEnd(s: string, i: number): number {
  const p = s.charCodeAt(i) === MINUS ? i + 1 : i;
  const c = s.charCodeAt(p);
  if (c === ZERO) return p + 1;
  return isDigit(c) ? skipWhile(s, p, isDigit) : NO;
}

/** Pushes the end after each `close` in the line-terminator-free run starting at `from`. */
function closerEnds(s: string, from: number, close: number, out: number[]): void {
  for (let p = from; p < s.length; p += 1) {
    const c = s.charCodeAt(p);
    if (c === close) out.push(p + 1);
    else if (isLineTerminator(c)) return;
  }
}

const isKeyQuote = (c: number): boolean => KEY_QUOTES.includes(c);

/**
 * Closing-quote positions of every parse of `Q(?:\\Q|[^Q])+Q` whose opening `Q` is at `a`.
 * A backslash before `Q` may be a lone unit (then `Q` closes) or pair with it.
 */
function closingQuotes(s: string, a: number): number[] {
  const closers: number[] = [];
  const reach = new Set<number>([a + 1]);
  for (let p = a + 1; reach.size > 0 && p < s.length; p += 1) {
    if (!reach.delete(p)) continue;
    const c = s.charCodeAt(p);
    if (isKeyQuote(c)) {
      if (p > a + 1) closers.push(p);
      continue;
    }
    reach.add(p + 1);
    if (c === BACKSLASH && isKeyQuote(s.charCodeAt(p + 1))) reach.add(p + 2);
  }
  return closers;
}

/**
 * Positions just after the `:` of every parse of
 * `\{[\s\xa0]*Q(?:\\Q|[^Q])+Q[\s\xa0]*:` at `i` (`Q` in `KEY_QUOTES`).
 */
function objectHeads(s: string, i: number): number[] {
  const a = skipWhile(s, i + 1, isDataSpace);
  if (!isKeyQuote(s.charCodeAt(a))) return [];
  const heads: number[] = [];
  for (const quote of closingQuotes(s, a)) {
    const colon = skipWhile(s, quote + 1, isDataSpace);
    if (s.charCodeAt(colon) === COLON) heads.push(colon + 1);
  }
  return heads;
}

function objectEnds(s: string, i: number): number[] {
  const out: number[] = [];
  for (const h of objectHeads(s, i)) closerEnds(s, h, RBRACE, out);
  return out;
}

/** The negative lookahead's body: is `s` at `i` a valid datum ending at the line end? */
function isValidJsonDatum(s: string, i: number): boolean {
  const ends = [plainIntegerEnd(s, i), scalarKeywordEnd(s, i)];
  const c = s.charCodeAt(i);
  if (c === QUOTE) ends.push(stringEnd(s, i));
  if (c === LBRACKET) ends.push(valueEnd(s, i));
  if (c === LBRACE && objectEnds(s, i).length > 0) ends.push(valueEnd(s, i));
  return ends.some((e) => e !== NO && atEndOrTerminator(s, e));
}

/** End of an exact lower-case `true`, `false` or `null`, or NO. */
function scalarKeywordEnd(s: string, i: number): number {
  const word = LITERALS.find((w) => s.startsWith(w, i));
  return word === undefined ? NO : i + word.length;
}

/** Ends of `-?\d+` (every digit prefix). */
function decimalEnds(s: string, i: number, out: number[]): void {
  const p = s.charCodeAt(i) === MINUS ? i + 1 : i;
  const stop = skipWhile(s, p, isDigit);
  for (let e = p + 1; e <= stop; e += 1) out.push(e);
}

/** Every `j` where `CO_JSON_DATA_INVALID` can match `s` from `i` to `j`. */
export function jsonDataInvalidEnds(s: string, i: number): number[] {
  if (isValidJsonDatum(s, i)) return [];
  const out: number[] = [];
  for (const word of LITERALS) {
    if (matchesAsciiFolded(s, i, word)) out.push(i + word.length);
  }
  decimalEnds(s, i, out);
  const c = s.charCodeAt(i);
  if (c === QUOTE) closerEnds(s, i + 1, QUOTE, out);
  if (c === LBRACKET) closerEnds(s, i + 1, RBRACKET, out);
  if (c === LBRACE) out.push(...objectEnds(s, i));
  return sortedUnique(out);
}
