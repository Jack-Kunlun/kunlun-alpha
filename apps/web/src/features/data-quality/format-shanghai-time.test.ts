import { describe, expect, it } from "vitest";
import { formatShanghaiTime } from "./format-shanghai-time";

describe("formatShanghaiTime", () => {
  it("renders UTC instants in Asia/Shanghai", () => {
    expect(formatShanghaiTime("2026-09-04T07:00:00.000Z")).toBe("2026-09-04 15:00:00（上海）");
  });

  it("uses unknown for null or malformed input", () => {
    expect(formatShanghaiTime(null)).toBe("未知");
    expect(formatShanghaiTime("not-a-time")).toBe("未知");
  });
});
