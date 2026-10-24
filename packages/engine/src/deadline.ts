// Ports `Deadline` from tools/interp/scan.py:51-82 (decision D5). JS regex calls cannot be
// interrupted, so the budget is checked cooperatively before each call. Browser-safe (D6):
// the default clock is `globalThis.performance.now`, not a Node import.

/** The per-block time budget is spent. */
export class BlockTimeout extends Error {
  constructor() {
    super("block time budget exhausted");
    this.name = "BlockTimeout";
  }
}

export type Clock = () => number;

const defaultClock: Clock = () => globalThis.performance.now();

/** A per-block budget in milliseconds, checked before every regex call. */
export class Deadline {
  readonly #clock: Clock;
  readonly #limit: number;

  constructor(timeoutMs: number, clock: Clock = defaultClock) {
    this.#clock = clock;
    this.#limit = clock() + timeoutMs;
  }

  /** Milliseconds left in the budget, floored at zero. */
  remainingMs(): number {
    return Math.max(0, this.#limit - this.#clock());
  }

  /** Throws `BlockTimeout` when the budget is spent. */
  check(): void {
    if (this.remainingMs() <= 0) {
      throw new BlockTimeout();
    }
  }

  /** Runs `re.test(text)`; throws `BlockTimeout` first when the budget is spent. */
  test(re: RegExp, text: string): boolean {
    this.check();
    return re.test(text);
  }
}
