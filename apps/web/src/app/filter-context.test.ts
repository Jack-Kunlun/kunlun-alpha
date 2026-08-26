import { describe, expect, it } from "vitest";
import {
  EMPTY_TERMINAL_FILTERS,
  parseTerminalFilters,
  serializeTerminalFilters,
  withTerminalFilters,
} from "./filter-context";

describe("terminal filter context v1", () => {
  it("normalizes point-in-time and canonical security filters", () => {
    const parsed = parseTerminalFilters(
      "?instrument=000001.sz&asOf=2026-08-24T15:00:00%2B08:00&instrument=600519.SH&instrument=600519.SH",
    );
    expect(parsed).toEqual({
      value: {
        version: "v1",
        asOf: "2026-08-24T07:00:00.000Z",
        instrumentIds: ["000001.SZ", "600519.SH"],
      },
      rejected: [],
    });
  });

  it("drops untrusted invalid query values with explicit rejection evidence", () => {
    const parsed = parseTerminalFilters("?asOf=tomorrow&instrument=AAPL&instrument=430047.BJ");
    expect(parsed.value.asOf).toBeNull();
    expect(parsed.value.instrumentIds).toEqual(["430047.BJ"]);
    expect(parsed.rejected).toEqual(["asOf", "instrument:AAPL"]);
  });

  it.each([
    "2026-02-30T07:00:00.000Z",
    "2026-08-24T24:00:00Z",
    "2026-08-24T07:00:00+24:00",
    "2026-08-24T07:00:00+08:60",
  ])("rejects an invalid RFC3339 calendar or time value: %s", (asOf) => {
    const parsed = parseTerminalFilters(`?asOf=${encodeURIComponent(asOf)}`);
    expect(parsed.value.asOf).toBeNull();
    expect(parsed.rejected).toEqual(["asOf"]);
  });

  it("accepts a valid leap day without calendar normalization", () => {
    expect(parseTerminalFilters("?asOf=2024-02-29T23:59:59.999Z").value.asOf).toBe(
      "2024-02-29T23:59:59.999Z",
    );
  });

  it("round-trips a stable query and leaves empty navigation clean", () => {
    const filters = parseTerminalFilters(
      "?instrument=600519.SH&asOf=2026-08-24T07:00:00.000Z",
    ).value;
    expect(parseTerminalFilters(`?${serializeTerminalFilters(filters)}`).value).toEqual(filters);
    expect(withTerminalFilters("/ranking", filters)).toContain("/ranking?asOf=");
    expect(withTerminalFilters("/ranking", EMPTY_TERMINAL_FILTERS)).toBe("/ranking");
  });
});
