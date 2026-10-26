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
