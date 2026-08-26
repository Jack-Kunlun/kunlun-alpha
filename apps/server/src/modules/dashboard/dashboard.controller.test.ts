import { BadRequestException } from "@nestjs/common";
import { describe, expect, it } from "vitest";
import { DashboardController } from "./dashboard.controller";
import { PublicReadDashboardAuthorizer } from "./dashboard-authorizer";
import type { DashboardRepository } from "./dashboard-repository";
import { DashboardService } from "./dashboard.service";

const repository: DashboardRepository = {
  loadMarketOverview: async () => ({
    indices: [],
    breadth: null,
    turnover: null,
    emotion: null,
    sourceVersions: [],
    evidenceIds: [],
  }),
};

describe("DashboardController", () => {
  it("maps invalid point-in-time input to 400", async () => {
    const controller = new DashboardController(
      new DashboardService(repository, new PublicReadDashboardAuthorizer()),
    );
    await expect(controller.marketOverview({ asOf: "not-a-time" })).rejects.toThrow(
      BadRequestException,
    );
  });
});
