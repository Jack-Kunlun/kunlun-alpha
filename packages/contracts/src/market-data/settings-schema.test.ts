import schema from "../../schemas/market-data/settings.json";
import { describe, expect, it } from "vitest";

describe("market-data settings schema", () => {
  it("keeps browser responses and updates closed", () => {
    const defs = schema.$defs;
    const update = defs.MarketDataSettingsUpdateRequest;
    const worker = defs.MarketDataWorkerSettingsResponse;
    expect(schema.additionalProperties).toBe(false);
    expect(update.additionalProperties).toBe(false);
    expect(worker.additionalProperties).toBe(false);
    expect(schema.required).toEqual([
      "schemaVersion",
      "provider",
      "revision",
      "tokenConfigured",
      "updatedAt",
    ]);
    expect(update.required).toEqual([
      "schemaVersion",
      "expectedRevision",
      "provider",
      "tokenAction",
    ]);
  });

  it("expresses token action semantics in the authoritative JSON Schema", () => {
    const update = schema.$defs.MarketDataSettingsUpdateRequest;
    expect(update.allOf).toHaveLength(2);
    expect(JSON.stringify(update)).toContain('"const":"REPLACE"');
    expect(JSON.stringify(update)).toContain('"enum":["KEEP","CLEAR"]');
  });
});
