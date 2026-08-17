import { BadRequestException, ForbiddenException } from "@nestjs/common";
import { describe, expect, it } from "vitest";
import { DataQualityController } from "./data-quality.controller";
import { DataQualityService } from "./data-quality.service";
import { InMemoryQualityRepository } from "./in-memory-quality.repository";
import type { DataQualityRecord } from "./quality-record";
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
];

const denyAll: DataQualityAuthorizer = { canAccess: () => false };

function controllerWith(authorizer?: DataQualityAuthorizer): DataQualityController {
  const service = new DataQualityService(new InMemoryQualityRepository(records), authorizer);
  return new DataQualityController(service);
}

describe("DataQualityController", () => {
  it("lists records by delegating to the service", async () => {
    const result = await controllerWith().list({});
    expect(result).toHaveLength(1);
  });

  it("maps invalid filters to 400", async () => {
    await expect(
      controllerWith().list({ unifiedCode: "SH.600519" } as never),
    ).rejects.toThrow(BadRequestException);
  });

  it("maps authorization failure to 403", async () => {
    await expect(controllerWith(denyAll).list({})).rejects.toThrow(ForbiddenException);
  });

  it("returns evidence through a safe internal id", async () => {
    const result = await controllerWith().evidence("fund-conflict-aaa");
    expect(result).toBeNull();
  });
});
