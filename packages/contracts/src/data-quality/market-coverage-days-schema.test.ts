import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const schemaPath = resolve(process.cwd(), "schemas/data-quality/market-coverage-days.json");

describe("market coverage days contract", () => {
  it("is a closed, bounded observed-only response with explicit single-source scope", () => {
    const schema = JSON.parse(readFileSync(schemaPath, "utf8")) as {
      title: string;
      additionalProperties: boolean;
      required: string[];
      properties: Record<string, { const?: string; maxItems?: number }>;
      $defs: Record<string, { additionalProperties?: boolean; enum?: string[] }>;
    };

    expect(schema.title).toBe("MarketCoverageDaysResponse");
    expect(schema.additionalProperties).toBe(false);
    expect(schema.required).toEqual([
      "schemaVersion",
      "scope",
      "meaning",
      "window",
      "unifiedCode",
      "source",
      "days",
    ]);
    expect(schema.properties["schemaVersion"]?.const).toBe("market-data-coverage-days-v1");
    expect(schema.properties["scope"]?.const).toBe("DAILY_RAW_SINGLE_SUPPORTED_SOURCE");
    expect(schema.properties["meaning"]?.const).toBe("OBSERVED_ONLY");
    expect(schema.properties["days"]?.maxItems).toBe(366);
    expect(schema.$defs["MarketCoverageObservedDay"]?.additionalProperties).toBe(false);
    expect(schema.$defs["MarketCoverageDaysWindow"]?.additionalProperties).toBe(false);
    expect(schema.$defs["MarketCoverageDaysSource"]?.enum).toEqual([
      "tushare-pro",
      "akshare-tencent",
      "akshare-sina",
      "akshare-eastmoney",
    ]);
  });
});
