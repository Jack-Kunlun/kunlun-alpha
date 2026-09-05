import { BadRequestException, ForbiddenException } from "@nestjs/common";
import { describe, expect, it } from "vitest";
import { DataQualityController } from "./data-quality.controller";
import { DataQualityService } from "./data-quality.service";
import { InMemoryQualityRepository } from "./in-memory-quality.repository";
import type { DataQualityAuthorizer } from "./data-quality.authorizer";
import type { MarketCoverageClock } from "./market-coverage.query";
import type { MarketCoverageDaysReadModel } from "./market-coverage-days.read-model";

const clock: MarketCoverageClock = { now: () => new Date("2026-09-05T02:00:00.000Z") };
const readModel: MarketCoverageDaysReadModel = { query: async () => [] };

function controllerWith(authorizer?: DataQualityAuthorizer): DataQualityController {
  return new DataQualityController(
    new DataQualityService(
      new InMemoryQualityRepository(),
      authorizer,
      undefined,
      clock,
      undefined,
      readModel,
    ),
  );
}

describe("DataQualityController market coverage days", () => {
  it("returns the generated object response and maps validation to 400", async () => {
    await expect(
      controllerWith().coverageDays({ unifiedCode: "600519.SH", source: "tushare-pro" }),
    ).resolves.toMatchObject({
      schemaVersion: "market-data-coverage-days-v1",
      days: [],
    });
    await expect(
      controllerWith().coverageDays({ unifiedCode: "600519.SH" } as never),
    ).rejects.toThrow(BadRequestException);
  });

  it("preserves authorization failures as forbidden", async () => {
    await expect(
      controllerWith({ canAccess: () => false }).coverageDays({ unknown: "x" } as never),
    ).rejects.toThrow(ForbiddenException);
  });
});
