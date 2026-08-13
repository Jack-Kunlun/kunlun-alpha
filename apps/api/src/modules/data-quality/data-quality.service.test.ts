import { describe, expect, it } from "vitest";
import { DataQualityService } from "./data-quality.service";
import type { DataQualityRecord } from "./quality-record";

const records: DataQualityRecord[] = [
  {
    id: "q1",
    kind: "NEGATIVE_PRICE",
    date: "2026-08-13",
    source: "provider-x",
    unifiedCode: "SH.600000",
    detail: "close must be >= 0",
    evidenceLink: "raw://objects/abc123",
  },
  {
    id: "q2",
    kind: "MISSING_DATE",
    date: "2026-08-14",
    source: "provider-y",
    unifiedCode: null,
    detail: "no calendar data",
    evidenceLink: "raw://objects/def456",
  },
];

describe("DataQualityService", () => {
  it("returns all records without a filter", () => {
    const service = new DataQualityService(records);
    expect(service.query()).toHaveLength(2);
  });

  it("filters by date", () => {
    const service = new DataQualityService(records);
    expect(service.query({ date: "2026-08-13" }).map((r) => r.id)).toEqual(["q1"]);
  });

  it("filters by source", () => {
    const service = new DataQualityService(records);
    expect(service.query({ source: "provider-y" }).map((r) => r.id)).toEqual(["q2"]);
  });

  it("filters by instrument and links raw evidence", () => {
    const service = new DataQualityService(records);
    const result = service.query({ unifiedCode: "SH.600000" });
    expect(result).toHaveLength(1);
    expect(result[0]!.evidenceLink).toContain("raw://objects/");
  });
});
