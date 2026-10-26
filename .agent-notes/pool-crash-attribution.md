## Observation: the pool crash-attribution race was deterministic
- **Context**: #6, `packages/engine/src/pool.ts`, test "does not charge a crash after a
  result to the next queued job".
- **Finding**: With two jobs queued on one worker and the first scheduling a crash in
  `setImmediate`, the second job got status `error` in 5 of 5 runs. The worker's
  `result` message reaches the pool before its `error` event, so the old `onMessage`
  always dispatched the next job before the crash arrived. The batch-5 note rated this
  Medium and timing-dependent; it is not. Fixed by a worker `idle` message (posted from
  `setImmediate` after each result) and a `settling` state in the pool, with a stall timer
  of `killGraceMs` so a worker that never goes idle is replaced without charging a job.
- **Impact**: Work scheduled by a job with timers or I/O (not immediates) can still land
  after `idle`; the engine core is synchronous and schedules nothing, so only test hooks
  do this. `worker.ts` `startWorker` never shows in vitest coverage: it runs inside the
  worker thread from the tsc build in a temp dir, which is not instrumented.
- **Confidence**: High
