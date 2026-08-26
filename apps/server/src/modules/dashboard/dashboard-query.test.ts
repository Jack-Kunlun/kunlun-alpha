import { describe, expect, it } from "vitest";
import { DashboardValidationError, validateMarketOverviewQuery } from "./dashboard-query";

describe("market overview query", () => {
  const now = new Date("2026-08-26T04:00:00.000Z");

  it("uses a current point-in-time when asOf is absent", () => {
    expect(validateMarketOverviewQuery({}, now)).toEqual({
      asOf: "2026-08-26T04:00:00.000Z",
      mode: "CURRENT",
    });
  });

  it("canonicalizes an explicit historical point-in-time", () => {
    expect(validateMarketOverviewQuery({ asOf: "2026-08-25T15:00:00+08:00" }, now)).toEqual({
      asOf: "2026-08-25T07:00:00.000Z",
      mode: "HISTORICAL",
    });
  });

  it.each([
    { asOf: "" },
    { asOf: "2026-02-30T07:00:00Z" },
    { asOf: "2026-08-25T24:00:00Z" },
    { asOf: "2026-08-27T00:00:00Z" },
    { rawSql: "DROP" },
  ])("rejects an invalid or unsupported query: %o", (query) => {
    expect(() => validateMarketOverviewQuery(query, now)).toThrow(DashboardValidationError);
  });
});
