import type { InstrumentDailyBar } from "@kunlun/shared-types";
import { describe, expect, it } from "vitest";
import { summarizeInstrumentBars } from "./instrument-bars-summary";

function bar(date: string, high: string, low: string, close: string): InstrumentDailyBar {
  return {
    date,
    eventTime: `${date}T07:00:00.000Z`,
    open: close,
    high,
    low,
    close,
    volume: "100",
    amount: "1000.00",
    suspended: false,
    dataVersion: "bars-v2",
    source: "akshare-eastmoney",
    sourceVersion: "2026.08.29",
    evidenceId: `evidence-${date}`,
    availableTime: `${date}T08:00:00.000Z`,
    processingTime: `${date}T08:01:00.000Z`,
  };
}

describe("summarizeInstrumentBars", () => {
  it("keeps price strings exact and rounds period change to two percentage decimals", () => {
    const summary = summarizeInstrumentBars([
      bar("2026-08-01", "10.5000", "9.5000", "10.0000"),
      bar("2026-08-02", "11.7500", "10.2500", "11.2345"),
    ]);

    expect(summary).toEqual({
      latestClose: "11.2345",
      periodChangePercent: "+12.35%",
      periodHigh: "11.7500",
      periodLow: "9.5000",
    });
  });

  it("returns null for an empty region and supports negative change", () => {
    expect(summarizeInstrumentBars([])).toBeNull();
    expect(
      summarizeInstrumentBars([
        bar("2026-08-01", "12.00", "9.00", "10.00"),
        bar("2026-08-02", "10.00", "8.00", "9.00"),
      ])?.periodChangePercent,
    ).toBe("-10.00%");
  });
});
