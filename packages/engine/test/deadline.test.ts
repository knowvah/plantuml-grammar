import { describe, expect, it, vi } from "vitest";
import { BlockTimeout, Deadline } from "../src/deadline.js";

function fakeClock(start: number): { now: () => number; set: (v: number) => void } {
  let t = start;
  return { now: () => t, set: (v) => void (t = v) };
}

describe("Deadline", () => {
  it("runs the regex while budget remains", () => {
    const clock = fakeClock(0);
    const d = new Deadline(100, clock.now);
    expect(d.test(/^a$/u, "a")).toBe(true);
    expect(d.test(/^a$/u, "b")).toBe(false);
  });

  it("throws BlockTimeout without calling the regex once the budget is spent", () => {
    const clock = fakeClock(0);
    const d = new Deadline(100, clock.now);
    clock.set(100);
    const re = /^a$/u;
    const spy = vi.spyOn(re, "test");
    expect(() => d.test(re, "a")).toThrow(BlockTimeout);
    expect(spy).not.toHaveBeenCalled();
  });

  it("reports remaining milliseconds, never below zero", () => {
    const clock = fakeClock(10);
    const d = new Deadline(50, clock.now);
    clock.set(30);
    expect(d.remainingMs()).toBe(30);
    clock.set(500);
    expect(d.remainingMs()).toBe(0);
  });

  it("defaults to the performance clock", () => {
    const d = new Deadline(60_000);
    expect(d.remainingMs()).toBeGreaterThan(0);
    expect(d.remainingMs()).toBeLessThanOrEqual(60_000);
  });

  it("BlockTimeout has a stable name", () => {
    expect(new BlockTimeout().name).toBe("BlockTimeout");
  });
});
