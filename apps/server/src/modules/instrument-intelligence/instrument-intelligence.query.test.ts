import { describe, expect, it } from "vitest";
import {
  InstrumentIntelligenceValidationError,
  parseInstrumentIntelligenceQuery,
} from "./instrument-intelligence.query";

const clock = { now: () => new Date("2026-08-26T08:00:00.000Z") };

describe("instrument intelligence query", () => {
  it("captures current time once and never accepts an implicit latest fallback", () => {
    expect(parseInstrumentIntelligenceQuery({}, clock)).toEqual({
      mode: "CURRENT",
      requestedAsOf: "2026-08-26T08:00:00.000Z",
      effectiveAsOf: "2026-08-26T08:00:00.000Z",
      generatedAt: "2026-08-26T08:00:00.000Z",
    });
    expect(() =>
      parseInstrumentIntelligenceQuery({ mode: "HISTORICAL" }, clock),
    ).toThrow(InstrumentIntelligenceValidationError);
  });

  it("rejects future, unzoned and CURRENT asOf values", () => {
    expect(() =>
      parseInstrumentIntelligenceQuery({ asOf: "2026-08-26T08:00:01Z" }, clock),
    ).toThrow("future");
    expect(() =>
      parseInstrumentIntelligenceQuery({ asOf: "2026-08-26T08:00:00" }, clock),
    ).toThrow("timezone-aware");
    expect(() =>
      parseInstrumentIntelligenceQuery(
        { mode: "CURRENT", asOf: "2026-08-25T08:00:00Z" },
        clock,
      ),
    ).toThrow("must not provide");
  });
});
