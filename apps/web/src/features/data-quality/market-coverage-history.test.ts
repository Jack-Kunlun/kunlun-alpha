import { describe, expect, it } from "vitest";
import { validateMarketCoverageHistoryWindow } from "./market-coverage-history";

describe("market coverage history window", () => {
  it("accepts a single day and trims both dates", () => {
    expect(
      validateMarketCoverageHistoryWindow({ dateFrom: " 2026-10-22 ", dateTo: "2026-10-22" }),
    ).toEqual({ ok: true, window: { dateFrom: "2026-10-22", dateTo: "2026-10-22" } });
  });

  it("accepts exactly 366 inclusive calendar days across a leap year", () => {
    expect(
      validateMarketCoverageHistoryWindow({ dateFrom: "2024-01-01", dateTo: "2024-12-31" }).ok,
    ).toBe(true);
    expect(
      validateMarketCoverageHistoryWindow({ dateFrom: "2025-09-05", dateTo: "2026-09-05" }).ok,
    ).toBe(true);
  });

  it("rejects a 367-day window with an actionable field error", () => {
    expect(
      validateMarketCoverageHistoryWindow({ dateFrom: "2024-01-01", dateTo: "2025-01-01" }),
    ).toEqual({ ok: false, errors: { dateTo: "查询窗口最多为 366 个自然日（含起止日）" } });
  });

  it("requires both dates and rejects a reversed range", () => {
    expect(validateMarketCoverageHistoryWindow({ dateFrom: "", dateTo: "" })).toEqual({
      ok: false,
      errors: { dateFrom: "请选择开始日期", dateTo: "请选择结束日期" },
    });
    expect(
      validateMarketCoverageHistoryWindow({ dateFrom: "2026-10-23", dateTo: "2026-10-22" }),
    ).toEqual({ ok: false, errors: { dateTo: "结束日期不能早于开始日期" } });
  });

  it.each(["2026-02-29", "2026-04-31", "2026-13-01", "2026-1-01", "0000-01-01", "0099-01-01"])(
    "rejects malformed or API-incompatible civil date %s",
    (dateFrom) => {
      expect(validateMarketCoverageHistoryWindow({ dateFrom, dateTo: "2026-10-23" })).toEqual({
        ok: false,
        errors: { dateFrom: "请输入有效的开始日期" },
      });
    },
  );

  it("allows a future window to report observed-only empty data", () => {
    expect(
      validateMarketCoverageHistoryWindow({ dateFrom: "2027-02-28", dateTo: "2027-03-01" }).ok,
    ).toBe(true);
  });
});
