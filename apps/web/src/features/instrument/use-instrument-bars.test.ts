import { describe, expect, it } from "vitest";
import { instrumentBarsPath, instrumentBarsQuery } from "./use-instrument-bars";

describe("instrument bars API helpers", () => {
  it("uses the nested bars endpoint and bounded default query", () => {
    expect(instrumentBarsPath("600519.SH")).toBe("/v1/instrument-intelligence/600519.SH/bars");
    expect(instrumentBarsQuery(null)).toEqual({ mode: "CURRENT", limit: "250" });
    expect(instrumentBarsQuery("2026-08-25T08:00:00.000Z", 500)).toEqual({
      mode: "HISTORICAL",
      asOf: "2026-08-25T08:00:00.000Z",
      limit: "500",
    });
  });
});
