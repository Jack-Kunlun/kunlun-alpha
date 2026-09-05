import { BadRequestException, ForbiddenException, Module } from "@nestjs/common";
import { NestFactory } from "@nestjs/core";
import { describe, expect, it } from "vitest";
import { DataQualityController } from "./data-quality.controller";
import { DataQualityService } from "./data-quality.service";
import { InMemoryQualityRepository } from "./in-memory-quality.repository";
import type { DataQualityAuthorizer } from "./data-quality.authorizer";
import type { MarketCoverageClock } from "./market-coverage.query";
import type { MarketCoverageReadModel } from "./market-coverage.read-model";

const clock: MarketCoverageClock = {
  now: () => new Date("2026-09-05T02:00:00.000Z"),
};

const readModel: MarketCoverageReadModel = {
  query: async () => ({ rows: [], truncated: false }),
};

function controllerWith(authorizer?: DataQualityAuthorizer): DataQualityController {
  return new DataQualityController(
    new DataQualityService(new InMemoryQualityRepository(), authorizer, readModel, clock),
  );
}

describe("DataQualityController market coverage", () => {
  it("receives the coverage route through Nest runtime injection", async () => {
    @Module({
      controllers: [DataQualityController],
      providers: [
        {
          provide: DataQualityService,
          useValue: {
            query: async () => [],
            getEvidence: async () => null,
            coverage: async () => ({}),
          },
        },
      ],
    })
    class DataQualityControllerTestModule {}

    const application = await NestFactory.createApplicationContext(
      DataQualityControllerTestModule,
      { logger: false },
    );
    try {
      await expect(application.get(DataQualityController).coverage({})).resolves.toEqual({});
    } finally {
      await application.close();
    }
  });

  it("delegates the object response and maps invalid filters to 400", async () => {
    await expect(controllerWith().coverage({ date: "2026-09-04" })).resolves.toMatchObject({
      schemaVersion: "market-data-coverage-v1",
      rows: [],
    });
    await expect(controllerWith().coverage({ unknown: "x" } as never)).rejects.toThrow(
      BadRequestException,
    );
  });

  it("preserves authorization failures as forbidden", async () => {
    await expect(controllerWith({ canAccess: () => false }).coverage({})).rejects.toThrow(
      ForbiddenException,
    );
  });
});
