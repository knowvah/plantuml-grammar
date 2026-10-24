## Observation: conformance goldens and their shape
- **Context**: T14 `tools/validate/conformance.py`
- **Finding**: 3,370 cases: 3,068 fixture cases (1,534 blocks × raw/non-raw) and 302
  toy cases; ok 1,697 / reject 1,673, no timeout or error under the default 10 s
  timeout. Three fixtures (`tests/fixtures/document/forms/{no-end,start-uppercase,
  start-without-keyword}.puml`) have no `@start…@end` block for `split_blocks`, so no
  goldens. Goldens use `ensure_ascii`, so U+E100 shows as ``. Toy JSONL lines may
  carry `start_map` (needed to pick a model); `fixture` is `toy/<name>`.
- **Impact**: T16 reads `tests/conformance/fixtures.jsonl` and `toy/*.jsonl` and must
  honour `start_map`. Regenerate with `uv run python -m tools.validate.conformance`;
  `--check` fails on drift.
- **Confidence**: High

## Observation: only three toy YAML files load alone
- **Context**: T14 toy engine sets
- **Finding**: In `tests/interp/fixtures/`, only `dottoy`, `preproctoy` and `shared` load
  alone; `seqtoy` and `classtoy` include `shared`, so the `toys` set resolves the whole
  directory together, as the Python tests do. `load_dir` orders models by filename
  (`welcome-strict` before `welcome`). T13's hand-generated toys differ from the real
  emitter only in `pin`, join prefixes (permissive) and that `model_order`.
- **Impact**: Compare engine JSONs by `model_order`, never by `list(models)`: the
  `models` object is key-sorted.
- **Confidence**: High

## Observation: fork pool shares the resolved model
- **Context**: T14 generator parallelism
- **Finding**: `multiprocessing.get_context("fork")` after `resolve(load_dir("model"))`
  shares the resolved model copy-on-write; 12 workers regenerate all goldens in ~17 s
  (about 58 s CPU serial). Unix-only.
- **Impact**: Reuse for any whole-fixture Python sweep.
- **Confidence**: High

## Observation: readline async iterator drops early lines
- **Context**: T15 `packages/engine/src/cli.ts`
- **Finding**: `for await` over `readline.createInterface(...)` loses lines emitted
  before the async iterator is created and then hangs at EOF; `main` awaited
  `pool.started` first, so piped stdin hung. Fix: take `[Symbol.asyncIterator]()` at
  creation. `parseArgs` treats `--workers -1` as a missing value (usage error), while
  `--workers=-1` gives the "positive integer" message.
- **Impact**: Any Node stdin reader that awaits before iterating.
- **Confidence**: High

## Observation: worker-thread tests need compiled JS and are not covered by V8
- **Context**: T15 pool and CLI tests
- **Finding**: `worker_threads` needs `.js`, so tests compile `src/` with
  `tsc --outDir <tmp>` (~1 s per test file; `test/helpers/pool-env.ts`). V8 coverage does
  not instrument worker threads, so `worker.ts` reports ~54% even though it runs; its
  in-process functions are tested directly. A worker's engine load is ~16 ms
  (`JSON.parse` + `loadEngine`); regex compile cost lands on its first jobs. The kill
  timer starts at the worker's `ready` message.
- **Impact**: Do not chase `worker.ts` coverage; keep the overall floor.
- **Confidence**: High

## Observation: crash attribution race in the pool
- **Context**: T15 crash tests
- **Finding**: A worker crash that lands just after it posted a result can be charged
  to the next job dispatched to that worker, which then gets an `error` verdict. Tests
  wait for the "worker crashed" log before sending the next job.
- **Impact**: An unexplained `error` mismatch in the T17 lane may be this race, not a
  port bug.
- **Confidence**: Medium
