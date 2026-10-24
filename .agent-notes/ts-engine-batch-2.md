## Observation: JS back reference to an unset group matches empty
- **Context**: T5 named back references in the JS translator
- **Finding**: In JS, `\k<n>` to a group that did not participate matches the empty
  string; Java and Python `regex` fail the match. The translator cannot detect this.
  Every model back reference today (packet `pkzp`/`pknp`, EBNF `ebca`/`ebmid`) refers to
  a group that always participates before the reference.
- **Impact**: A future model regex with a back reference into an optional or alternative
  group can diverge between Python and TS. Conformance (T16) would show it.
- **Confidence**: High

## Observation: model leaf counts for the JS translator
- **Context**: T5 model-wide compile test
- **Finding**: 986 unique (regex, ci) pairs; 5 contain `(?(`/`(?&` (T9). 16 atomic and
  only 2 possessive leaves (naive greps for possessives report ~9, mostly false
  positives). `resolve(load_dir("model"))` takes over 2 minutes (~177k leaf nodes).
- **Impact**: Budget test time for model-wide sweeps; use the real counts in later tasks.
- **Confidence**: High

## Observation: JS `\s`/`trim()` differ from Python whitespace
- **Context**: T6 source.ts port
- **Finding**: Python `isspace()`/`strip()` cover 29 code points including U+001C-U+001F
  and U+0085 but not U+FEFF; JS `\s`/`trim()` include U+FEFF and omit those. The test
  file `tests/interp/test_source.py` contains literal NBSP bytes that render as spaces.
- **Impact**: Never use `\s` or `trim()` as a stand-in for Python whitespace in the port.
- **Confidence**: High
