import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const schemaPath = resolve(process.cwd(), "schemas/data-quality/market-coverage.json");

describe("market coverage contract", () => {
  it("keeps the response closed, bounded, and explicitly observed-only", () => {
    const schema = JSON.parse(readFileSync(schemaPath, "utf8")) as {
      additionalProperties: boolean;
      properties: Record<string, { const?: string; maxItems?: number }>;
      required: string[];
      $defs: Record<string, { additionalProperties: boolean }>;
    };

    expect(schema.additionalProperties).toBe(false);
    expect(schema.required).toEqual([
      "schemaVersion",
      "scope",
      "meaning",
      "window",
      "rows",
      "truncated",
    ]);
    expect(schema.properties["schemaVersion"]?.const).toBe("market-data-coverage-v1");
    expect(schema.properties["scope"]?.const).toBe("DAILY_RAW_SUPPORTED_SOURCES");
    expect(schema.properties["meaning"]?.const).toBe("OBSERVED_ONLY");
    expect(schema.properties["rows"]?.maxItems).toBe(100);
    expect(schema.$defs["MarketCoverageWindow"]?.additionalProperties).toBe(false);
    expect(schema.$defs["MarketCoverageRow"]?.additionalProperties).toBe(false);
  });
});
