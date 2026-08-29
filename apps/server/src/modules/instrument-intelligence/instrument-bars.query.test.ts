import { describe, expect, it } from "vitest";
import {
  InstrumentIntelligenceValidationError,
  parseInstrumentBarsQuery,
} from "./instrument-intelligence.query";

const clock = { now: () => new Date("2026-08-26T08:00:00.000Z") };

describe("instrument bars query", () => {
  it("defaults to current point-in-time and 250 daily bars", () => {
    expect(parseInstrumentBarsQuery({}, clock)).toEqual({
      mode: "CURRENT",
      requestedAsOf: "2026-08-26T08:00:00.000Z",
      effectiveAsOf: "2026-08-26T08:00:00.000Z",
      generatedAt: "2026-08-26T08:00:00.000Z",
      limit: 250,
    });
  });

  it("accepts a bounded historical limit", () => {
    expect(
      parseInstrumentBarsQuery(
        {
          mode: "HISTORICAL",
          asOf: "2026-08-25T08:00:00Z",
          limit: "500",
        },
        clock,
      ),
    ).toMatchObject({
      mode: "HISTORICAL",
      effectiveAsOf: "2026-08-25T08:00:00.000Z",
      limit: 500,
    });
  });

  it.each(["0", "501", "1.5", "-1", "01", "500 ", ""])("rejects invalid limit %s", (limit) => {
    expect(() => parseInstrumentBarsQuery({ limit }, clock)).toThrow(
      InstrumentIntelligenceValidationError,
    );
  });

  it("rejects unsupported keys and future historical points", () => {
    expect(() => parseInstrumentBarsQuery({ unknown: "x" }, clock)).toThrow(
      InstrumentIntelligenceValidationError,
    );
    expect(() => parseInstrumentBarsQuery({ asOf: "2026-08-26T08:00:01Z" }, clock)).toThrow(
      "future",
    );
  });
});
