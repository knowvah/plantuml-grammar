## Observation: npm test needs uv and the Python environment
- **Context**: First CI run of `.github/workflows/ci.yml` (PR #7); the `node` job had Node only.
- **Finding**: The TextMate proof (`tests/textmate/fixtures/helpers.mjs`, `emitGrammar` and
  `loadYamlGrammar`) runs `uv run python -m tools.emit.textmate`. Without uv on PATH the
  spawn fails with ENOENT; `run()` reports only `result.stderr`, which is unset, so the
  message reads `... failed:\nundefined` and hides the cause (`result.error`).
- **Impact**: Any job or machine that runs `npm test` needs uv and `uv sync`. A clean-clone
  check with uv on PATH does not catch a missing uv; reproduce with
  `env -i PATH="<node dir>:/usr/bin:/bin" node --test "tests/textmate/**/*.test.mjs"`.
  Reporting `result.error` in `run()` would make the message name the missing command.
- **Confidence**: High

## Observation: the Python suite spent 80% of its time reloading the model
- **Context**: Profiling the `python` CI job (11 min, pytest 615 s), 2026-10-26.
- **Finding**: `load_dir(model/)` + `resolve` takes ~14 s (YAML 2-3 s, JSON-schema
  validation ~4 s, `resolve` 5 s, and `load_dir` itself runs `resolve` once more as
  validation). 31 test modules each did it in a module-scoped fixture or a `@cache`d
  function, ~6.5 min of the 8.4 min local run; genuine test work was ~1.5 min.
  `tests/helpers/models.py` now caches both per process: 506 s -> 149 s serial on one
  core, 50 s with `-n 4` (pytest-xdist, `--dist loadfile`, in `addopts`). Inside
  `resolve`, 1,793 patched entries are each validated with `jsonschema` in
  `tools/model/patch.py::_refine`; that is most of its 5 s and the next lever.
  `tests/helpers/engine_build.py` serialises `npm run build -w packages/engine` across
  workers with `fcntl.flock`, because `engine_dist` and `ts_engine.ensure_built` would
  otherwise write `packages/engine/dist` concurrently.
- **Impact**: `ubuntu-latest` has 4 vCPUs, so CI pytest should drop from ~10 min to
  about 1 min. Run `pytest -n 0` for a serial run (profiling, debugging).
- **Confidence**: High (timed runs; `--durations`)
