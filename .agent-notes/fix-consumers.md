## Observation: join semantics counted in units, smallest k wins
- **Context**: Implementing `join` in tools/interp/scan.py (`scan_join`).
- **Finding**: k counts units (an embedded `{{ }}` group is one unit), checked for k = 1..max_lines+1 with lines joined by U+E100; the first full match wins, so a `parts` that matches at k=1 never consumes more lines. Rule.advance now does the start-line match itself (join rules have no separate first-line check).
- **Impact**: Family tasks must make `parts` of join entries require the joiner where k>1 is meant; toy fixture classtoy.yaml has CommandWrap/WrapFar/WrapOpt.
- **Confidence**: High

## Observation: emitter approximations of the new contract
- **Finding**: TextMate: join = `match`, bracket default end `^\s*\}` kept; ci regex = `(?i:...)`. Real class diagram `class Foo / Foo --> Bar` is accepted by the interpreter with default dispatch (gen-class-diagram).
- **Confidence**: High
