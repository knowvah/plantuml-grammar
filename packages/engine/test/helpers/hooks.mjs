// Test-only worker hook (Pool `hookModule`): misbehaves on marker texts.
export const SPIN = "spin";
export const THROW = "throw";
export const EXIT = "exit";
export const EXIT_CODE = 3;
export const CRASH_AFTER = "crash-after";

export function beforeJob(job) {
  if (job.text === SPIN) for (;;);
  if (job.text === THROW) throw new Error("boom");
  if (job.text === EXIT) process.exit(EXIT_CODE);
  if (job.text === CRASH_AFTER) setImmediate(() => { throw new Error("late crash"); });
}
