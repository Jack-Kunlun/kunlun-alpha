import { describe, expect, it } from "vitest";
import { dashboardAuthorizerFor, dashboardDailySymbolsFor } from "./dashboard.module";

describe("dashboard deployment authorization", () => {
  it("fails closed unless public terminal read is explicitly enabled", async () => {
    expect(await dashboardAuthorizerFor(undefined).canAccess()).toBe(false);
    expect(await dashboardAuthorizerFor("deny").canAccess()).toBe(false);
    expect(await dashboardAuthorizerFor("public").canAccess()).toBe(true);
    expect(() => dashboardAuthorizerFor("allow")).toThrow(
      "DASHBOARD_TERMINAL_READ_POLICY must be deny or public",
    );
  });
});

describe("dashboard daily sample configuration", () => {
  it("keeps daily mode opt-in when the environment variable is absent", () => {
    expect(dashboardDailySymbolsFor(undefined)).toBeUndefined();
  });

  it("accepts one through one hundred unique canonical SH/SZ symbols", () => {
    expect(dashboardDailySymbolsFor("000001.SZ,600519.SH")).toEqual(["000001.SZ", "600519.SH"]);
    const hundred = Array.from(
      { length: 100 },
      (_, index) => `${String(index + 1).padStart(6, "0")}.SZ`,
    );
    expect(dashboardDailySymbolsFor(hundred.join(","))).toEqual(hundred);
  });

  it.each([
    ["", "DASHBOARD_DAILY_SYMBOLS must contain 1 to 100 unique canonical SH/SZ symbols"],
    [
      "600519.SH,600519.SH",
      "DASHBOARD_DAILY_SYMBOLS must contain 1 to 100 unique canonical SH/SZ symbols",
    ],
    ["600519.BJ", "DASHBOARD_DAILY_SYMBOLS must contain 1 to 100 unique canonical SH/SZ symbols"],
    [
      "600519.SH, bad",
      "DASHBOARD_DAILY_SYMBOLS must contain 1 to 100 unique canonical SH/SZ symbols",
    ],
  ])("rejects an invalid sample list %s", (raw, message) => {
    expect(() => dashboardDailySymbolsFor(raw)).toThrow(message);
  });

  it("rejects more than one hundred symbols", () => {
    const oneHundredOne = Array.from(
      { length: 101 },
      (_, index) => `${String(index + 1).padStart(6, "0")}.SZ`,
    );
    expect(() => dashboardDailySymbolsFor(oneHundredOne.join(","))).toThrow(
      "DASHBOARD_DAILY_SYMBOLS must contain 1 to 100 unique canonical SH/SZ symbols",
    );
  });
});
