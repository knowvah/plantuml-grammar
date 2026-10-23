## Observation: BlockVerdict optional keys were the origin of most Pyright errors
- **Context**: fixing the Pyright errors at tests/families/test_activity3.py:528-530.
- **Finding**: the same `reportTypedDictNotRequiredAccess` error came from ~100 reads in
  tests and in `tools/validate/parity_run.py`. `BlockVerdict` was `total=False`, but
  `Oracle.java` (block JSON writer) and `oracle._error_verdict` write every key except
  `error`. The type is now total with `error: NotRequired[str]`; project Pyright errors
  went from 129 to 32, with no new ones.
- **Impact**: Pyright is not a CI gate here (no config, not in package.json or CI). 32 errors
  remain, mostly Optional access and argument types in tests, plus
  `tools/interp/engine.py:261`, `tools/model/java_regex.py`,
  `tools/model/load.py`, `tools/validate/parity.py:237` and `tools/validate/parity_run.py:99`.
- **Confidence**: High (pyright before/after error lists diffed)

## Observation: remaining lizard warnings in tools/
- **Finding**: `lizard -C 10 -L 30 -a 5 -w tools/` flags 9 functions on main, none in
  `tools/emit/`. Over CCN 10: `translate/run.py:render_files` (16, also 43 NLOC),
  `translate/iregex.py:_split_alternatives` (12), `translate/dedupe.py:_assign_owners` (12) and
  `dedupe` (11), `interp/engine.py:_run` (12). Over 30 NLOC: `translate/run.py:build_rules`,
  `translate/ubrex_gantt.py:sentence_notes`. Params: `interp/engine.py:_candidate` (7);
  `validate/parity_run.py:collect_jobs` (5, at the limit).
- **Impact**: candidates for a further cleanup PR; `tools/translate` is generator code that
  runs only when regenerating `model/generated/`.
- **Confidence**: High (lizard)
