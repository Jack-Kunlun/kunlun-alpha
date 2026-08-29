import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const schema = JSON.parse(readFileSync("schemas/instrument/bars.json", "utf8")) as Record<
  string,
  unknown
>;

describe("instrument daily bars response contract", () => {
  it("pins a closed, research-only point-in-time response", () => {
    expect(schema["title"]).toBe("InstrumentBarsResponse");
    expect(schema["additionalProperties"]).toBe(false);
    expect(JSON.stringify(schema)).toContain("instrument-bars-v1");
    expect(JSON.stringify(schema)).toContain("RESEARCH_ONLY_NO_REAL_ORDER_PATH");
  });

  it("requires PIT query metadata, daily raw bars and aggregate provenance", () => {
    expect(schema["required"]).toEqual(
      expect.arrayContaining([
        "schemaVersion",
        "dataMeaning",
        "instrumentId",
        "mode",
        "requestedAsOf",
        "effectiveAsOf",
        "interval",
        "priceType",
        "status",
        "barCount",
        "dataCutoffTime",
        "freshnessSeconds",
        "bars",
        "sourceVersions",
        "evidenceIds",
      ]),
    );
    const bar = (schema["definitions"] as Record<string, unknown>)["InstrumentDailyBar"] as Record<
      string,
      unknown
    >;
    expect(bar["additionalProperties"]).toBe(false);
    expect(bar["required"]).toEqual(
      expect.arrayContaining([
        "date",
        "eventTime",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "suspended",
        "availableTime",
        "processingTime",
        "source",
        "sourceVersion",
        "dataVersion",
        "evidenceId",
      ]),
    );
    expect((schema["properties"] as Record<string, Record<string, unknown>>)["interval"]).toEqual({
      const: "DAILY",
    });
    expect((schema["properties"] as Record<string, Record<string, unknown>>)["priceType"]).toEqual({
      const: "RAW",
    });
  });
});
