## Observation: first-verdict latency is regex compilation, concentrated in a few patterns
- **Context**: Diagnosing #4, 2026-10-26, Node 26.9.0 (V8) on macOS, Apple silicon.
  `npm run bench -w packages/engine -- --runs 5 --patterns`: one fresh process per run,
  load the engine, judge the family's first accepted conformance golden twice.
- **Finding**:
  - `loadEngine` takes ~13 ms; no `RegExp` is built at load (`RuleBook` compiles a
    context on first use). The ~250 ms + ~1.7 s in #4 came from a probe that built and
    ran every model's `main` context eagerly.
  - First verdict (median of 5, ms): REGEX 1070, GANTT 469, TIMING 464, HELP 423,
    CLASS 328, DESCRIPTION 297, ACTIVITY 293, STATE 247, CHEN_EER 67, PACKET 43; the
    other 25 families <= 25 (SEQUENCE 23).
  - The cost is V8 compiling each regex on its first `test`, growing with pattern size
    (0.5-2.4 ms per KB here). `new RegExp` itself is cheap except in GANTT (~130 ms).
  - The second identical `accepts` (30-98 ms in six families; ~0.2 ms on the third) is
    V8 regexp tier-up: the pattern is recompiled to native code on its second execution.
    Under `node --no-regexp-tier-up` or `--regexp-interpret-all` the second call drops to
    0.1-0.4 ms (REGEX, GANTT, CLASS).
  - Patterns that dominate:
    - REGEX: `RegexLineWellFormed` (RX_WELL_FORMED expanded at depth 8, 464,884 B),
      ~1.0-1.1 s alone; it is tested on every line of `meta-diagrams-regex/main`.
    - `@startuml` blocks: dispatch tries the UML factories in PSystemBuilder order, so a
      TIMING, HELP, ACTIVITY or DESCRIPTION block also builds `class/main`. Its join
      prefixes (CommandCreateClassMultilinesBracketNextLine 58,796 B, the package bracket
      joins 45,679 B, CommandCreateJsonBlock 45,225 B) and the 140,273 B `fast` path of
      CommandCreateJsonSingleLineError's split cost ~190 ms together.
    - GANTT: the natural-language task and resource sentences (92,620, 47,177,
      35,952 B). CHEN_EER: six `*Checked` starts of ~39.5 KB each.
- **Impact**: Shrinking or skipping these few patterns fixes #4; nothing else is large.
  Browsers cannot set V8 flags, so tier-up cost only shrinks with the patterns.
- **Confidence**: High for the attribution (per-regex timing, V8 flag A/B); timings vary
  +-10% between runs and by machine.

## Observation: guards cut first-verdict latency; join prefixes are wider than Python
- **Context**: Fix 1 of #4 (`tools/emit/guard.py`), 2026-10-26, same machine and bench.
- **Finding**: 39 patterns of >= 8 KB get a guard (<= ~3 KB; prefix guards are the
  largest); engine JSON +21 KB raw, +0.8 KB gzip. Median first verdict before -> after (ms):
  GANTT 469 -> 68, CLASS 328 -> 103, ACTIVITY 293 -> 123, DESCRIPTION 297 -> 122,
  STATE 247 -> 142, TIMING 464 -> 235, HELP 423 -> 225, CHEN_EER 67 -> 29; REGEX unchanged
  (~1.05 s, RX_WELL_FORMED runs on every line, so no guard helps). Engine equality stayed
  0 mismatches on all three corpora; conformance goldens unchanged. Eleven large patterns
  get no guard (no head within 1 KB, or a head that matches the empty string; not
  inspected one by one), e.g. PacketZeroWidthRow's 30 KB join prefix, CreoleLine 14 KB.
  Comparing guarded with unguarded matchers is the wrong oracle for join prefixes: the
  unguarded prefix regex (`js_prefix`) widens `X+ rest` to `X* (p(X) | rest)` on purpose
  (`tools/model/js_prefix.py:386`), so it accepts e.g. `jsonDiagram {` + U+E100 for the
  JSON block join although Python's partial match rejects it; the guard rejects it too.
  The check is "accepts everything Python's partial match accepts".
- **Impact**: Remaining first-verdict cost in TIMING/HELP is many mid-size (<10 KB)
  patterns, not one large one. REGEX needs fix 2 (native RX_WELL_FORMED).
- **Confidence**: High (bench medians of 5; corpus-wide guard check; parity run)

## Observation: RX_WELL_FORMED as a native parser; the regex is deterministic
- **Context**: Fix 2 of #4 (`packages/engine/src/native-regex.ts`), 2026-10-26.
- **Finding**: Every repetition in the RX_* DEFINE grammar is possessive (`*+`, `++`) and
  every alternation is decided by its first character (`\` `[` `(` ... ), so a greedy
  recursive-descent parse with no backtracking equals the Python `regex` fullmatch; the
  only greedy-but-backtrackable piece, the class body `(?:[^\]\\\x00]|\\.)+`, cannot
  consume `]` so backtracking never changes the end. Two Python-side details matter:
  `to_python` turns `\Z` into "optional one line terminator, then end", so `[ab\n` is
  well formed and so is `[ab\r\nx` (the class body matches terminators); and `.` is
  `[^\n\r\x85  ]`, so `\` + NUL is an escape. A first recursive version
  overflowed the stack at ~5,000 nested groups; the parser keeps an explicit stack of
  "where this group's alternation ends if the next atom fails". Result: REGEX first verdict
  1,070 ms -> 11 ms; engine JSON 4.38 MB -> 3.84 MB (149 -> 118 KB gzip). A native kind
  may now have no `fast` regex (`js_subroutines.FAST_DEPTHS`, `fast_depth`).
- **Impact**: Adding a native leaf: digest in `_NATIVE_KINDS`, `_FAST_FINAL`,
  `FAST_DEPTHS`; `NATIVE_KINDS` in matcher.ts; a differential test against
  `python_original`. The remaining first-verdict cost (TIMING/HELP ~230 ms) is many
  mid-size patterns; `(?i:)` modifiers are the next lever.
- **Confidence**: High (4,000 random + edge inputs, fixture lines, corpus lines, parity)

## Observation: `(?i:)` modifiers do not shorten the first verdict; the remaining cost is factory try-order
- **Context**: Fix 3 candidate of #4, measured 2026-10-27 on 1.0.2 (Node 26.9.0, same
  machine and bench). A compile hook rewrote every `[aA]` letter pair in the engine's
  patterns to `(?i:...)` runs (a lone pair before a quantifier becomes `(?i:a)+`), end to
  end inside `accepts`, 5 fresh processes per mode; plus fresh-process micro A/B of the
  top three patterns of TIMING and HELP.
- **Finding**: medians orig -> rewritten (ms): TIMING 233 -> 225, HELP 218 -> 221,
  STATE 141 -> 141, DESCRIPTION 123 -> 122, ACTIVITY 120 -> 121, CLASS 101 -> 100,
  GANTT 63 -> 66, CHEN_EER 29 -> 35, CREOLE 24 -> 19: all within run-to-run noise, with
  0 compile fallbacks and every verdict unchanged. The pairs are 672 KB of the 2.04 MB of
  pattern source (167,848 pairs); the rewrite removes 10-33% of the bytes a family compiles
  (TIMING 347 -> 303 KB) and shrinks the engine JSON 3.84 -> 3.49 MB raw, 118 -> 110 KB
  gzip, but V8's compile cost tracks the automaton, not the source bytes: the top
  patterns cost the same with 0 pair bytes (6,121 B, 8.8 ms, no letters) as with 5,200
  (9,589 B, 6.9 ms). Where TIMING's 232 ms goes: 302 patterns compiled (ctor 43 ms, first
  calls 157 ms, later calls 25 ms); 3 patterns >= 5 ms (24 ms), 36 at 1-5 ms (68 ms), 72 at
  0.3-1 ms (49 ms), 191 under 0.3 ms (16 ms). By model, a `@startuml` TIMING block pays
  for the factories tried before it: class 37 ms (24 patterns), sequence 24 ms (47),
  activity3 14 ms (46), activity-legacy 29 ms (20), description 26 ms (16), state 10 ms
  (11), timing itself 10 ms (11); CLASS compiles 162 patterns for 100 ms. One single-line
  command, `single-line-dedication`, costs 16 ms alone (6,121 B, `new RegExp` 7 ms + first
  test 9 ms: `(?=[\x00-\u{10ffff}]{26})` and an astral-aware length lookahead under `u`),
  tried on every `@startuml` block.
- **Impact**: `(?i:)` emission is not worth a PR for #4 (size-only win, 8 KB gzip). The
  remaining levers are the number of patterns a UML block compiles before its factory
  (dispatch order / cheaper rejection of the factories tried first) and a few single
  expensive patterns (dedication 16 ms, the 9,459 B `@version` class pattern 9 ms, the
  9,589 B 7 ms one); tier-up (`second` 15-40 ms) is V8's and not reducible in browsers.
  Scripts: scratchpad `ci-ab.mjs`, `ci-dump.mjs`, `by-model.mjs` (not committed).
- **Confidence**: High for the null result (end-to-end and per-pattern A/B agree, 5 runs);
  Medium for the per-model split (a pattern shared by several models is attributed to all).
