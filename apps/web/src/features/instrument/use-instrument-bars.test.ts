import { describe, expect, it } from "vitest";
import {
  instrumentBarsPath,
  instrumentBarsQuery,
  bindInstrumentBarsResult,
} from "./use-instrument-bars";
import type { InstrumentBarsResponse } from "@kunlun/shared-types";

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

describe("bars request binding", () => {
  const response = { instrumentId: "600519.SH" } as InstrumentBarsResponse;
  const result = {
    status: "success" as const,
    data: { requestKey: "600519.SH|CURRENT|250", response },
    error: null,
  };
  it("retains only the response belonging to the current query", () => {
    expect(bindInstrumentBarsResult(result, "600519.SH|CURRENT|250")).toEqual({
      status: "success",
      data: response,
      error: null,
    });
  });
  it("hides an old response when security, point in time or window changes", () => {
    for (const key of [
      "000001.SZ|CURRENT|250",
      "600519.SH|2026-08-25T08:00:00.000Z|250",
      "600519.SH|CURRENT|20",
    ]) {
      expect(bindInstrumentBarsResult(result, key)).toEqual({
        status: "loading",
        data: null,
        error: null,
      });
    }
  });
  it("preserves an unavailable result without exposing any prior data", () => {
    const error = new Error("读取失败");
    expect(
      bindInstrumentBarsResult({ status: "forbidden", data: null, error }, "600519.SH|CURRENT|250"),
    ).toEqual({ status: "forbidden", data: null, error });
  });
});
