import { ForbiddenException } from "@nestjs/common";
import { describe, expect, it } from "vitest";
import {
  PublicReadDashboardAuthorizer,
  type DashboardAuthorizer,
} from "./dashboard-authorizer";
import type { DashboardRepository, MarketOverviewRepositoryData } from "./dashboard-repository";
import { DashboardService } from "./dashboard.service";

function dataAt(dataTime: string): MarketOverviewRepositoryData {
  return {
    indices: [
      {
        instrumentId: "000001.SH",
        name: "上证指数",
        dataTime,
        value: "3100.0000",
        previousClose: "3090.0000",
        changeBps: 32,
        sourceVersion: "bars-v2",
        evidenceId: "index-evidence",
      },
    ],
    breadth: {
      dataTime,
      advancingCount: 2,
      decliningCount: 1,
      unchangedCount: 1,
      suspendedCount: 0,
      sampleSize: 4,
      advancingRatioBps: 5000,
      universeVersion: "ashare-code-pattern-v1",
      sourceVersions: ["bars-v2"],
      evidenceIds: ["breadth-evidence"],
    },
    turnover: {
      dataTime,
      amountCny: "123456789.00",
      sampleSize: 4,
      sourceVersions: ["bars-v2"],
      evidenceIds: ["breadth-evidence"],
    },
    emotion: {
      dataTime,
      scoreBps: 5200,
      confidenceBps: 8000,
      sampleSize: 100,
      algorithmVersion: "emotion-score-v1",
      sourceVersions: ["emotion-v1"],
      evidenceIds: ["emotion-evidence"],
    },
    sourceVersions: ["bars-v2", "emotion-v1"],
    evidenceIds: ["breadth-evidence", "emotion-evidence", "index-evidence"],
  };
}

describe("DashboardService", () => {
  it("returns a complete historical snapshot without pretending it is live", async () => {
    const repository: DashboardRepository = {
      loadMarketOverview: async () => dataAt("2026-08-25T06:59:30.000Z"),
    };
    const result = await new DashboardService(
      repository,
      new PublicReadDashboardAuthorizer(),
    ).marketOverview({
      asOf: "2026-08-25T07:00:00.000Z",
    });
    expect(result.mode).toBe("HISTORICAL");
    expect(result.freshness.status).toBe("HISTORICAL");
    expect(result.completeness).toBe("COMPLETE");
    expect(result.risk.state).toBe("WATCH");
    expect(result.dataMeaning).toBe("RESEARCH_ONLY_NO_REAL_ORDER_PATH");
  });

  it("marks stale current data and refuses to infer a current risk state", async () => {
    const repository: DashboardRepository = {
      loadMarketOverview: async (asOf) =>
        dataAt(new Date(Date.parse(asOf) - 10 * 60_000).toISOString()),
    };
    const result = await new DashboardService(
      repository,
      new PublicReadDashboardAuthorizer(),
    ).marketOverview({});
    expect(result.freshness.status).toBe("STALE");
    expect(result.risk.state).toBe("UNKNOWN");
  });

  it("preserves an explicit empty state instead of fabricating zero metrics", async () => {
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
    const result = await new DashboardService(
      repository,
      new PublicReadDashboardAuthorizer(),
    ).marketOverview({
      asOf: "2026-08-25T07:00:00.000Z",
    });
    expect(result.completeness).toBe("EMPTY");
    expect(result.freshness.status).toBe("NO_DATA");
    expect(result.risk.state).toBe("UNKNOWN");
  });

  it("enforces the dashboard authorization boundary", async () => {
    const repository: DashboardRepository = {
      loadMarketOverview: async () => dataAt("2026-08-25T07:00:00.000Z"),
    };
    const deny: DashboardAuthorizer = { canAccess: () => false };
    await expect(new DashboardService(repository, deny).marketOverview({})).rejects.toThrow(
      ForbiddenException,
    );
  });

  it.each([
    [90, "FRESH"],
    [91, "DELAYED"],
    [300, "DELAYED"],
    [301, "STALE"],
  ] as const)("classifies a current cutoff age of %ss as %s", async (age, status) => {
    const repository: DashboardRepository = {
      loadMarketOverview: async (asOf) =>
        dataAt(new Date(Date.parse(asOf) - age * 1000).toISOString()),
    };
    const result = await new DashboardService(
      repository,
      new PublicReadDashboardAuthorizer(),
    ).marketOverview({});
    expect(result.freshness.status).toBe(status);
  });

  it("uses the oldest component time and rejects repository future leakage", async () => {
    const mixedRepository: DashboardRepository = {
      loadMarketOverview: async (asOf) => {
        const data = dataAt(new Date(Date.parse(asOf) - 30_000).toISOString());
        if (data.breadth !== null && data.turnover !== null) {
          const old = new Date(Date.parse(asOf) - 301_000).toISOString();
          data.breadth.dataTime = old;
          data.turnover.dataTime = old;
        }
        return data;
      },
    };
    const mixed = await new DashboardService(
      mixedRepository,
      new PublicReadDashboardAuthorizer(),
    ).marketOverview({});
    expect(mixed.freshness.status).toBe("STALE");

    const futureRepository: DashboardRepository = {
      loadMarketOverview: async (asOf) => dataAt(new Date(Date.parse(asOf) + 1_000).toISOString()),
    };
    await expect(
      new DashboardService(
        futureRepository,
        new PublicReadDashboardAuthorizer(),
      ).marketOverview({}),
    ).rejects.toThrow("point-in-time cutoff");
  });
});
