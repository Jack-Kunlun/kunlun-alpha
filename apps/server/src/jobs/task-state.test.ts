import { describe, expect, it } from "vitest";
import { canRetry, isTerminal, type TaskStatus } from "./task-state";

describe("task-state", () => {
  it("classifies terminal states", () => {
    const statuses: TaskStatus[] = ["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "DEAD"];
    expect(statuses.filter(isTerminal)).toEqual(["SUCCEEDED", "DEAD"]);
  });

  it("allows retry for pending and failed", () => {
    expect(canRetry("PENDING")).toBe(true);
    expect(canRetry("FAILED")).toBe(true);
    expect(canRetry("RUNNING")).toBe(false);
    expect(canRetry("SUCCEEDED")).toBe(false);
    expect(canRetry("DEAD")).toBe(false);
  });
});
