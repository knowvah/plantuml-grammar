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
