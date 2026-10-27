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
