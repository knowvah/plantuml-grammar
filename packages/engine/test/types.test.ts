import { describe, expect, it } from "vitest";
import {
  ENGINE_FORMAT,
  STATUS_ERROR,
  STATUS_OK,
  STATUS_REJECT,
  STATUS_TIMEOUT,
} from "../src/types.js";

describe("contract constants", () => {
  it("pins the engine format", () => {
    expect(ENGINE_FORMAT).toBe(1);
  });

  it("defines the four statuses", () => {
    expect([STATUS_OK, STATUS_REJECT, STATUS_TIMEOUT, STATUS_ERROR]).toEqual([
      "ok",
      "reject",
      "timeout",
      "error",
    ]);
  });
});
