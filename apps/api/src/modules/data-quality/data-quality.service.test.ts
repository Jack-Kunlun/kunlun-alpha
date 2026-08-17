import { ForbiddenException } from "@nestjs/common";
import { describe, expect, it } from "vitest";
import { DataQualityService } from "./data-quality.service";
import { InMemoryQualityRepository } from "./in-memory-quality.repository";
import type { DataQualityRecord, EvidenceRecord } from "./quality-record";
import { QualityValidationError } from "./quality-filters";
import type { DataQualityAuthorizer } from "./data-quality.authorizer";

const records: DataQualityRecord[] = [
  {
    id: "fund-conflict-aaa",
    kind: "SOURCE_CONFLICT",
    unifiedCode: "600519.SH",
    date: "2026-08-13",
    source: "provider-a",
    detail: "多来源观测不一致，未选择权威值",
    createdAt: "2026-08-13T09:30:00.000Z",
    availableAt: "2026-08-13T09:30:00.000Z",
    schemaVersion: "fund-v1",
  },
  {
    id: "fund-conflict-bbb",
    kind: "SOURCE_CONFLICT",
    unifiedCode: "518880.SH",
    date: "2026-08-14",
    source: "provider-b",
    detail: "多来源观测不一致，未选择权威值",
    createdAt: "2026-08-14T09:30:00.000Z",
    availableAt: null,
    schemaVersion: "fund-v1",
  },
];

const evidence: EvidenceRecord[] = [
  { id: "ev-1", source: "provider-a", schemaVersion: "fund-v1", availableAt: "2026-08-13T09:30:00.000Z" },
];

const denyAll: DataQualityAuthorizer = { canAccess: () => false };

describe("DataQualityService", () => {
  it("queries through a repository port rather than an injected array", async () => {
    const service = new DataQualityService(new InMemoryQualityRepository(records));
    expect(await service.query({})).toHaveLength(2);
  });

  it("queries an arbitrary historical date and suffix-form code", async () => {
    const service = new DataQualityService(new InMemoryQualityRepository(records));
    const result = await service.query({ date: "2026-08-13", unifiedCode: "600519.SH" });
    expect(result.map((r) => r.id)).toEqual(["fund-conflict-aaa"]);
  });

  it("rejects the legacy prefix form SH.600519", async () => {
    const service = new DataQualityService(new InMemoryQualityRepository(records));
    await expect(service.query({ unifiedCode: "SH.600519" })).rejects.toThrow(QualityValidationError);
  });

  it("rejects illegal dates", async () => {
    const service = new DataQualityService(new InMemoryQualityRepository(records));
    await expect(service.query({ date: "2026-13-45" })).rejects.toThrow(QualityValidationError);
  });

  it("rejects unknown filter keys", async () => {
    const service = new DataQualityService(new InMemoryQualityRepository(records));
    await expect(service.query({ evil: "x" })).rejects.toThrow(QualityValidationError);
  });

  it("propagates repository failure instead of fabricating empty success", async () => {
    const failingRepository = {
      query: async () => {
        throw new Error("database unavailable");
      },
      getEvidence: async () => null,
    };
    const service = new DataQualityService(failingRepository);
    await expect(service.query({})).rejects.toThrow("database unavailable");
  });

  it("returns a controlled forbidden response when unauthorized", async () => {
    const service = new DataQualityService(new InMemoryQualityRepository(records), denyAll);
    await expect(service.query({})).rejects.toThrow(ForbiddenException);
  });

  it("resolves evidence only through a safe internal id", async () => {
    const service = new DataQualityService(new InMemoryQualityRepository(records, evidence));
    const result = await service.getEvidence("ev-1");
    expect(result?.id).toBe("ev-1");
    expect(result?.source).toBe("provider-a");
  });

  it("rejects unsafe evidence identifiers", async () => {
    const service = new DataQualityService(new InMemoryQualityRepository(records, evidence));
    await expect(service.getEvidence("../../etc/passwd")).rejects.toThrow(QualityValidationError);
    await expect(service.getEvidence("raw/objects/abc")).rejects.toThrow(QualityValidationError);
  });
});
