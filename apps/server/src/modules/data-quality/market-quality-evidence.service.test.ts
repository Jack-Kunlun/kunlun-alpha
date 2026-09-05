import { ForbiddenException, NotFoundException, ServiceUnavailableException } from "@nestjs/common";
import { describe, expect, it } from "vitest";
import { DataQualityService } from "./data-quality.service";
import { InMemoryQualityRepository } from "./in-memory-quality.repository";
import type { DataQualityAuthorizer } from "./data-quality.authorizer";
import {
  MarketQualityEvidenceNotFoundError,
  type MarketQualityEvidenceReadModel,
} from "./market-quality-evidence.read-model";

const snapshotId = "a".repeat(64);
const page = {
  schemaVersion: "market-quality-evidence-v1" as const,
  snapshotId,
  publishedAt: "2026-09-01T01:02:00.000Z",
  snapshotRecordCount: 0,
  matchingRecordCount: 0,
  offset: 0,
  limit: 20,
  hasMore: false,
  records: [],
};
const detail = {
  schemaVersion: "market-quality-evidence-v1" as const,
  snapshotId,
  publishedAt: page.publishedAt,
  record: {
    evidenceId: `mqe-${"b".repeat(64)}`,
    source: "akshare-tencent" as const,
    unifiedCode: "600519.SH",
    interval: "DAILY" as const,
    requestedStart: "2026-08-01",
    requestedEnd: "2026-08-31",
    status: "REJECTED" as const,
    reasonCode: "BAR_QUALITY_REJECTED" as const,
    captureAvailableAt: "2026-09-01T01:00:00.000Z",
    qualityRecordedAt: "2026-09-01T01:01:00.000Z",
    rejectedRecordCount: 1,
    qualityEventCount: 0,
    filteredRecordCount: 0,
    qualityEvents: [],
    filteredRecords: [],
  },
};

const model: MarketQualityEvidenceReadModel = {
  list: async () => page,
  detail: async () => detail,
};
const denyAll: DataQualityAuthorizer = { canAccess: () => false };

function service(
  authorizer?: DataQualityAuthorizer,
  readModel: MarketQualityEvidenceReadModel = model,
): DataQualityService {
  return new DataQualityService(
    new InMemoryQualityRepository(),
    authorizer,
    undefined,
    undefined,
    readModel,
  );
}

describe("DataQualityService market evidence", () => {
  it("authorizes before parsing or reading and returns the pinned page", async () => {
    await expect(service(denyAll).marketEvidence({ evil: "x" })).rejects.toBeInstanceOf(
      ForbiddenException,
    );
    await expect(service().marketEvidence({})).resolves.toEqual(page);
  });

  it("maps unavailable readers to a controlled 503 without exposing internals", async () => {
    const failing: MarketQualityEvidenceReadModel = {
      list: async () => {
        throw new Error("/private/secret-sentinel");
      },
      detail: async () => {
        throw new Error("/private/secret-sentinel");
      },
    };
    await expect(service(undefined, failing).marketEvidence({})).rejects.toEqual(
      new ServiceUnavailableException("行情质量证据暂不可用"),
    );
    await expect(
      service(undefined, failing).marketEvidenceDetail(detail.record.evidenceId, { snapshotId }),
    ).rejects.toEqual(new ServiceUnavailableException("行情质量证据暂不可用"));
  });

  it("returns safe details and maps absent records to 404", async () => {
    await expect(
      service().marketEvidenceDetail(detail.record.evidenceId, { snapshotId }),
    ).resolves.toEqual(detail);
    const missing: MarketQualityEvidenceReadModel = {
      list: async () => page,
      detail: async () => {
        throw new MarketQualityEvidenceNotFoundError();
      },
    };
    await expect(
      service(undefined, missing).marketEvidenceDetail(detail.record.evidenceId, { snapshotId }),
    ).rejects.toBeInstanceOf(NotFoundException);
  });
});
