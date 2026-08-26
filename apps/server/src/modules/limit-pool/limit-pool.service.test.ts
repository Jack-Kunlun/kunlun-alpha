import { ForbiddenException } from "@nestjs/common";
import { describe, expect, it } from "vitest";
import type { LimitPoolAuthorizer } from "./limit-pool-authorizer";
import type { LimitPoolRepository, StoredLimitPoolSnapshot } from "./limit-pool.repository";
import { LimitPoolService } from "./limit-pool.service";

function stored(): StoredLimitPoolSnapshot {
  return {
    tradingDate: "2026-08-25",
    eventTime: "2026-08-25T06:40:00.000Z",
    availableTime: "2026-08-25T06:40:01.000Z",
    revision: 2,
    algorithmVersion: "limit-pool-v2",
    ladderAlgorithmVersion: "board_ladder_v2",
    limitRuleVersion: "cn-limit-rules-v1",
    materializerVersion: "limit-pool-terminal-materializer-v1",
    sourceVersions: ["vendor-a:v7"],
    evidenceIds: ["limit-600000-1"],
    payload: {
      tradingDate: "2026-08-25",
      previousTradingDate: "2026-08-24",
      completeness: "COMPLETE",
      missingReasons: [],
      limitUpCount: 1,
      limitDownCount: 0,
      sealedCount: 1,
      totalOpenCount: 0,
      ladder: [{ streakDays: 2, count: 1, previousDayEligibleCount: 2, promotedCount: 1 }],
      entries: [
        {
          instrumentId: "600000.SH",
          name: "浦发银行",
          exchange: "SH",
          listingBoard: "MAIN",
          isSt: false,
          side: "LIMIT_UP",
          state: "SEALED",
          streakDays: 2,
          previousStreakDays: 1,
          openCount: 0,
          priceCny: "11.00",
          previousCloseCny: "10.00",
          firstSealTime: "2026-08-25T01:31:00.000Z",
          lastSealTime: "2026-08-25T01:31:00.000Z",
          eventTime: "2026-08-25T01:31:00.000Z",
          availableTime: "2026-08-25T01:31:01.000Z",
          revision: 1,
          sourceVersion: "vendor-a:v7",
          evidenceId: "limit-600000-1",
        },
      ],
    },
  };
}

const allow: LimitPoolAuthorizer = { canRead: () => true };

describe("LimitPoolService", () => {
  it("computes promotion rate and marks delayed current data explicitly", async () => {
    const repository: LimitPoolRepository = { findSnapshot: async () => stored() };
    const service = new LimitPoolService(repository, allow);
    const result = await service.getSnapshot(
      {},
      {
        mode: "CURRENT",
        asOf: "2026-08-25T06:42:00.000Z",
        algorithmVersion: undefined,
        ladderAlgorithmVersion: undefined,
        limitRuleVersion: undefined,
        materializerVersion: undefined,
      },
    );

    expect(result.freshness.status).toBe("DELAYED");
    expect(result.ladder[0]?.promotionRateBps).toBe(5000);
    expect(result.entries[0]?.algorithmVersion).toBe("limit-pool-v2");
    expect(result.ladder[0]?.algorithmVersion).toBe("board_ladder_v2");
    expect(result.entries[0]?.dataMeaning).toBe("LIMIT_POOL_ALGORITHM_OUTPUT");
  });

  it("returns an explicit empty projection instead of fabricated rows", async () => {
    const repository: LimitPoolRepository = { findSnapshot: async () => null };
    const service = new LimitPoolService(repository, allow);
    const result = await service.getSnapshot(
      {},
      {
        mode: "HISTORICAL",
        asOf: "2026-08-25T06:42:00.000Z",
        algorithmVersion: "limit-pool-v2",
        ladderAlgorithmVersion: "board_ladder_v2",
        limitRuleVersion: "cn-limit-rules-v1",
        materializerVersion: "limit-pool-terminal-materializer-v1",
      },
    );
    expect(result.completeness).toBe("EMPTY");
    expect(result.entries).toEqual([]);
    expect(result.freshness.status).toBe("NO_DATA");
  });

  it("fails closed when aggregate counts disagree with the evidence rows", async () => {
    const invalid = stored();
    invalid.payload.limitUpCount = 2;
    const service = new LimitPoolService({ findSnapshot: async () => invalid }, allow);
    await expect(
      service.getSnapshot(
        {},
        {
          mode: "CURRENT",
          asOf: "2026-08-25T06:42:00.000Z",
          algorithmVersion: undefined,
          ladderAlgorithmVersion: undefined,
          limitRuleVersion: undefined,
          materializerVersion: undefined,
        },
      ),
    ).rejects.toThrow("limit-up count does not match evidence rows");
  });

  it("fails closed when an embedded instrument observation is from the future", async () => {
    const invalid = stored();
    invalid.payload.entries[0]!.availableTime = "2026-08-25T06:43:00.000Z";
    const service = new LimitPoolService({ findSnapshot: async () => invalid }, allow);
    await expect(
      service.getSnapshot(
        {},
        {
          mode: "CURRENT",
          asOf: "2026-08-25T06:42:00.000Z",
          algorithmVersion: undefined,
          ladderAlgorithmVersion: undefined,
          limitRuleVersion: undefined,
          materializerVersion: undefined,
        },
      ),
    ).rejects.toThrow("instrument evidence is not point-in-time eligible");
  });

  it("fails closed when instrument evidence identity is duplicated", async () => {
    const invalid = stored();
    invalid.payload.entries.push({ ...invalid.payload.entries[0]! });
    invalid.payload.limitUpCount = 2;
    invalid.payload.sealedCount = 2;
    invalid.payload.ladder[0]!.count = 2;
    const service = new LimitPoolService({ findSnapshot: async () => invalid }, allow);
    await expect(
      service.getSnapshot(
        {},
        {
          mode: "CURRENT",
          asOf: "2026-08-25T06:42:00.000Z",
          algorithmVersion: undefined,
          ladderAlgorithmVersion: undefined,
          limitRuleVersion: undefined,
          materializerVersion: undefined,
        },
      ),
    ).rejects.toThrow("duplicate instrument evidence identity");
  });

  it("enforces terminal read authorization", async () => {
    const deny: LimitPoolAuthorizer = { canRead: () => false };
    const service = new LimitPoolService({ findSnapshot: async () => stored() }, deny);
    await expect(
      service.getSnapshot(
        {},
        {
          mode: "CURRENT",
          asOf: "2026-08-25T06:42:00.000Z",
          algorithmVersion: undefined,
          ladderAlgorithmVersion: undefined,
          limitRuleVersion: undefined,
          materializerVersion: undefined,
        },
      ),
    ).rejects.toBeInstanceOf(ForbiddenException);
  });
});
