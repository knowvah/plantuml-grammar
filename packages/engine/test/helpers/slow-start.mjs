// Test-only hook whose import blocks for 400 ms, simulating a slow engine load.
const LOAD_MS = 400;
Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, LOAD_MS);
export function beforeJob() {}
