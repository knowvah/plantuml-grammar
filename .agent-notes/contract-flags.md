## Observation: CommandChartGrid is `super(false, ...)` but registered by no factory
- **Context**: verifying the 24 `git grep 'super(false, '` commands against the extraction.
- **Finding**: 23 classes (25 instances; CommandWBSItemNew/Old occur twice each) carry `doTrim=false` in `extracted/`; CommandChartGrid is in no `initCommandsList`, so it has no rule.
- **Impact**: `trim: false` count in `model/generated` is 25 entries, not 24.
- **Confidence**: High

## Observation: the jar keeps tabs and trailing blanks; only BOM, U+2013 and line breaks are rewritten
- **Context**: `Line.text` for `trim: false`.
- **Finding**: `ReadLineReader.readLine` (preproc/ReadLineReader.java:89-102) drops a leading U+FEFF, maps U+2013 to `-`, and BufferedReader splits at `\n`, `\r`, `\r\n`. Oracle probes: `\t++ b` rejected, `++ b\t` accepted (the mindmap regex allows trailing `\s`), CRLF accepted, `--` en dash arrives as `--`. `Line.text` mirrors that (tools/interp/source.py `read_line`).
- **Confidence**: High (oracle probes in tests/interp/test_flags_trim.py, corpus-marked)

## Observation: gives/needs final-state failure is reported at the @end line, upstream scores it lowest
- **Context**: `PSystemBuilder.java:275-280` builds the crash error with `source.get(0)` and an empty trace.
- **Finding**: the interpreter reports the `@end` line (as the task specified) and `progress == len(body)`, which outranks every other factory failure in `_decide`; upstream would rank this crash below ordinary syntax errors. Only matters when several factories fail for one start keyword.
- **Confidence**: Medium (not probed against a multi-factory keyword)

## Observation: parity is unchanged by `trim: false`
- **Context**: A/B parity runs on one frozen copy of model/ (old vs regenerated gen-*), all 3 corpora.
- **Finding**: no verdict changed in any family; FR/FA equal the committed slices. Gap fixtures `mindmap-indented-plus` / `wbs-pseudo-trailing-blank` are now rejected by the interpreter (strict-xfail gap tests, if still present, would XPASS).
- **Confidence**: High
