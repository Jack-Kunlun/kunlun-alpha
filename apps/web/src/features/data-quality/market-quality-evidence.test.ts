import { describe, expect, it } from "vitest";
import {
  MarketQualityEvidenceResponseError,
  parseMarketQualityEvidenceDetail,
  parseMarketQualityEvidencePage,
} from "./market-quality-evidence";

const record = {
  evidenceId: `mqe-${"a".repeat(64)}`,
  source: "akshare-tencent",
  unifiedCode: "600519.SH",
  interval: "DAILY",
  requestedStart: "2026-08-01",
  requestedEnd: "2026-08-31",
  status: "REJECTED",
  reasonCode: "BAR_QUALITY_REJECTED",
  captureAvailableAt: "2026-09-01T01:00:00.123456Z",
  qualityRecordedAt: "2026-09-01T01:01:00Z",
  rejectedRecordCount: 1,
  qualityEventCount: 1,
  filteredRecordCount: 0,
  qualityEvents: [{ kind: "NEGATIVE_PRICE", unifiedCode: "600519.SH", timestamp: null }],
  filteredRecords: [],
};

const page = {
  schemaVersion: "market-quality-evidence-v1",
  snapshotId: "b".repeat(64),
  publishedAt: "2026-09-01T01:02:00.000001Z",
  snapshotRecordCount: 1,
  matchingRecordCount: 1,
  offset: 0,
  limit: 20,
  hasMore: false,
  records: [record],
};

describe("market quality evidence response boundary", () => {
  it("accepts generated fields with microsecond timestamps", () => {
    expect(parseMarketQualityEvidencePage(page).records[0]?.evidenceId).toBe(record.evidenceId);
    expect(
      parseMarketQualityEvidenceDetail({
        schemaVersion: "market-quality-evidence-v1",
        snapshotId: page.snapshotId,
        publishedAt: page.publishedAt,
        record,
      }).record.qualityRecordedAt,
    ).toBe(record.qualityRecordedAt);
  });

  it("rejects unknown fields, mismatched event codes, and forbidden detail text", () => {
    expect(() => parseMarketQualityEvidencePage({ ...page, extra: "secret-sentinel" })).toThrow(
      MarketQualityEvidenceResponseError,
    );
    expect(() =>
      parseMarketQualityEvidencePage({
        ...page,
        records: [{ ...record, qualityEvents: [{ ...record.qualityEvents[0], unifiedCode: "000001.SZ" }] }],
      }),
    ).toThrow(MarketQualityEvidenceResponseError);
    expect(() => parseMarketQualityEvidencePage({ ...page, extra: "secret-sentinel" })).not.toThrow(
      "secret-sentinel",
    );
    expect(() =>
      parseMarketQualityEvidencePage({
        ...page,
        records: [
          {
            ...record,
            source: "akshare-sina",
            filteredRecordCount: 1,
            filteredRecords: [
              {
                rawRowIndex: 1,
                timestamp: "2026-08-10T01:00:00.000Z",
                requestedStart: record.requestedStart,
                requestedEnd: record.requestedEnd,
                reasonCode: "SINA_OVERFETCH_OUTSIDE_REQUEST",
              },
            ],
          },
        ],
      }),
    ).toThrow(MarketQualityEvidenceResponseError);
    expect(() =>
      parseMarketQualityEvidencePage({
        ...page,
        records: [{ ...record, qualityRecordedAt: "2026-09-01T01:02:00.000002Z" }],
      }),
    ).toThrow(MarketQualityEvidenceResponseError);
  });
});
