## Observation: V8 compiles regexes lazily, so cold load understates first use
- **Context**: T12 Node probe in `tools.emit.build`
- **Finding**: Parsing `dist/plantuml.engine.json` plus `new RegExp` for the 659
  patterns of all diagram models' `main` contexts takes ~250 ms. The first `.test("")`
  of those same patterns takes ~1.7 s, because V8 compiles on first execution.
- **Impact**: The C1 load budget (≤1 s) is met as specified, but first-verdict latency
  is higher. Measure it in T15/T18; do not eagerly touch every pattern at load.
  `RuleBook` already builds a context's matchers on first use.
- **Confidence**: High

## Observation: largest patterns in the engine JSON
- **Context**: T12 build output
- **Finding**: Pattern sizes: 464,884 chars for the `RegexLineWellFormed` whole-line
  start (RX_WELL_FORMED at depth 8), 200,931 for the JSON block-body `fast` path,
  140,273 and 92,620 (Gantt task sentences) next. The largest join prefix is 58,796 B
  (class bracket join), under `js_prefix.MAX_PATTERN_BYTES` (64 KB). File: 4.36 MB raw,
  148 KB gzip, 787 patterns, 247 contexts.
- **Impact**: Size work, if ever needed, starts with RX_WELL_FORMED's depth.
- **Confidence**: High

## Observation: native JSON leaf detection is keyed by exact YAML source
- **Context**: T12 D3a split emission
- **Finding**: `native_kind` / `depth_for` match the resolved Part's `regex` string
  byte-for-byte (SHA-256 of the Java source). Any edit to the two JSON leaves in
  `model/diagrams/class-objects.yaml` turns them back into DEFINE patterns expanded at
  `MAX_DEPTH`, not native. A test recomputes the table from YAML and fails on drift.
  `_number_atomics` in `js_prefix` works on `_a@o`/`_a@c` placeholders; T12 rewrites
  leaf `_aN` names to them before composing.
- **Impact**: Editing those leaves needs `native.ts`, the digest table and
  `tests/model/test_native_json.py` updated together.
- **Confidence**: High

## Observation: unsupported patterns fail whole contexts, not single entries
- **Context**: T13 interpreter
- **Finding**: `RuleBook.rules(model, context)` builds every entry of a context at once,
  and `EngineModel.matcher(id)` throws `ModelError` for `{unsupported}`. So one
  unsupported pattern gives status `error` for every block that reaches its context,
  even when the block would never test that entry. Python behaves the same way.
  `loadEngine` rejects out-of-table pattern ids, so only a V8 stack-overflow `RangeError`
  can reach the interpreter as a runtime error; it maps to status `error`.
- **Impact**: Any future `unsupported` pattern is a whole-context outage; keep the
  emitter's unsupported count at 0.
- **Confidence**: High

## Observation: TS toy engine fixtures are generated, with permissive join prefixes
- **Context**: T13 `packages/engine/test/fixtures/engine-*.engine.json`
- **Finding**: Generated from the Python toy YAML (`tests/interp/fixtures` and the YAML
  snippets in `test_require_pop_reject.py`, `test_document_dispatch.py`,
  `test_plain_lines_empty_end.py`, `test_flags_trim.py`) with `to_js` and
  `line_pattern_js`, by an uncommitted scratch script. Every join prefix is
  `^(?:[^]*)$`, so only `max_lines` stops joins. Several models share one file and are
  chosen with `startMap`.
- **Impact**: T14's cross-check against the real emitter must expect the prefix
  difference; regenerate rather than hand-edit if the toys change.
- **Confidence**: High

## Observation: Deadline reads the clock once per regex test
- **Context**: T13 timeout and raw-mode tests
- **Finding**: `Deadline` reads the clock in its constructor and in every `check()` and
  `test()`, so a counting fake clock counts regex calls. Timeout tests use fake clocks:
  a real catastrophic regex cannot be interrupted in JS (D5).
- **Impact**: Use counting clocks to assert "once per block" style properties.
- **Confidence**: High

## Observation: shared pytest fixtures via `pytest_plugins` in test modules
- **Context**: T12 test split under `tests/emit/`
- **Finding**: `tests/emit/engine_support.py` holds session-scoped fixtures (`resolved`,
  `built`, `engine_file`); each `test_engine*.py` module declares
  `pytest_plugins = ["tests.emit.engine_support"]`, which avoids ruff F811 and a
  `conftest.py`. It emits one `PytestAssertRewriteWarning` (the helper has no asserts).
- **Impact**: Reuse this pattern; the 13 s model resolve then runs once per session.
- **Confidence**: High
