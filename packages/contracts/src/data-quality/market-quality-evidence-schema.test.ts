import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const schemaPath = resolve(process.cwd(), "schemas/data-quality/market-quality-evidence.json");

describe("market quality evidence contract", () => {
  it("freezes the sanitized record, storage snapshot, and response envelopes", () => {
    const schema = JSON.parse(readFileSync(schemaPath, "utf8")) as {
      additionalProperties: boolean;
      properties: Record<string, { const?: string; maxItems?: number }>;
      required: string[];
      $defs: Record<string, {
        additionalProperties?: boolean;
        properties?: Record<string, { maximum?: number; const?: string; maxItems?: number }>;
        required?: string[];
      }>;
    };

    expect(schema.additionalProperties).toBe(false);
    expect(schema.properties["schemaVersion"]?.const).toBe("market-quality-evidence-v1");
    expect(schema.properties["records"]?.maxItems).toBe(100);
    expect(schema.required).toEqual([
      "schemaVersion",
      "snapshotId",
      "publishedAt",
      "snapshotRecordCount",
      "matchingRecordCount",
      "offset",
      "limit",
      "hasMore",
      "records",
    ]);

    const record = schema.$defs["MarketQualityEvidenceRecord"];
    const snapshot = schema.$defs["MarketQualityEvidenceSnapshot"];
    const current = schema.$defs["MarketQualityEvidenceCurrent"];
    const detail = schema.$defs["MarketQualityEvidenceDetail"];
    expect(record?.additionalProperties).toBe(false);
    expect(record?.properties?.["qualityEvents"]).toBeTruthy();
    expect(record?.properties?.["filteredRecords"]).toBeTruthy();
    const filteredRecord = schema.$defs["MarketQualityFilteredRecord"];
    expect(filteredRecord?.properties?.["rawRowIndex"]?.maximum).toBe(9007199254740991);
    expect(snapshot?.additionalProperties).toBe(false);
    expect(snapshot?.properties?.["schemaVersion"]?.const).toBe("market-quality-snapshot-v1");
    expect(snapshot?.properties?.["records"]?.maxItems).toBe(10000);
    expect(current?.additionalProperties).toBe(false);
    expect(current?.properties?.["schemaVersion"]?.const).toBe("market-quality-current-v1");
    expect(detail?.additionalProperties).toBe(false);
    expect(detail?.properties?.["schemaVersion"]?.const).toBe("market-quality-evidence-v1");
  });

  it("does not expose raw identity, detail, request, payload, or path fields", () => {
    const schema = JSON.parse(readFileSync(schemaPath, "utf8")) as {
      $defs: Record<string, { properties?: Record<string, unknown> }>;
    };
    const recordProperties = Object.keys(schema.$defs["MarketQualityEvidenceRecord"]?.properties ?? {});
    const forbidden = [
      "captureId",
      "rawObjectId",
      "rawChecksum",
      "reasonDetail",
      "rejectedRecords",
      "request",
      "payload",
      "path",
      "token",
    ];
    expect(recordProperties.filter((field) => forbidden.includes(field))).toEqual([]);
  });
});
