import { describe, expect, it } from "vitest";
import { formatShanghaiTime, shanghaiLocalToIso } from "./limit-pool-terminal-page";

describe("limit-pool Asia/Shanghai time boundary", () => {
  it("interprets datetime-local as Shanghai wall time regardless of browser zone", () => {
    expect(shanghaiLocalToIso("2026-08-25T14:42")).toBe("2026-08-25T06:42:00.000Z");
  });

  it("renders UTC evidence in Asia/Shanghai explicitly", () => {
    expect(formatShanghaiTime("2026-08-25T06:42:00.000Z")).toContain("2026/08/25 14:42:00");
  });
});
