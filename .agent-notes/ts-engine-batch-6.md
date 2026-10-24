## Observation: TS engine equals Python on every golden and corpus job
- **Context**: T16 conformance test and the batch-6 TS lane gate
- **Finding**: 0 mismatches over 3,370 fixture + 302 toy goldens on the first run, and
  0 Python/TS mismatches over vega (301 blocks), plantuml-ts (4,401) and pdiff (5,834)
  with `--engine both`; TS totals equal Python's (FR 0/0/0, FA 0/32/47, same
  diagram-mismatch and raw-FR counts, 0 timeouts). TS judge wall time was 1.9/4.5/9.6 s
  vs Python 15.0/20.9/23.1 s (4 workers each).
- **Impact**: Baseline for later model changes: a nonzero
  `reports/engine-equality-<corpus>.json` `mismatches` after a model edit is a
  translator gap or engine divergence, not noise.
- **Confidence**: High

## Observation: reading fixture text like Python in TS
- **Context**: T16 `test/helpers/conformance.ts`
- **Finding**: Python `Path.read_text()` translates `\r\n` and `\r` to `\n` and keeps a
  leading BOM (UTF-8, not utf-8-sig). `TextDecoder` strips the BOM, so the helper uses
  `Buffer.toString("utf8")` plus a newline replace before `splitBlocks`.
- **Impact**: Any TS caller comparing with Python on file input must normalise the same
  way; the engine itself takes text and does not normalise.
- **Confidence**: High

## Observation: vitest `describe.skipIf` still runs its callback
- **Context**: T16 empty-root skip
- **Finding**: The callback of `describe.skipIf(cond)` runs at collection even when
  skipped, so file reads inside it throw ENOENT. Register the suite only when inputs
  exist, else one `test.skip("<message>")`.
- **Impact**: Guard any file I/O at registration time in skippable suites.
- **Confidence**: High

## Observation: the TS lane builds the package on demand
- **Context**: T17 `tools/validate/ts_engine.py`
- **Finding**: `--engine ts|both` rebuilds `packages/engine/dist/` when `dist/cli.js` is
  older than the newest `src/**/*.ts` (dist is gitignored, so a fresh checkout builds
  once). A missing `dist/plantuml.engine.json` raises `TsEngineError`; nothing
  regenerates it. Request ids are `<job index>:l2` / `<job index>:raw`; TS slices go to
  `reports/parity-ts/<corpus>/`. A request with no CLI result becomes an `error`
  verdict; a non-zero CLI exit or overrun raises `TsEngineError` (exit 2).
- **Impact**: Run `uv run python -m tools.emit.build` before the lane after a model
  edit, or the lane judges a stale engine.
- **Confidence**: High
