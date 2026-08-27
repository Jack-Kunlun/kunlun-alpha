import type { PreciousMetalFund } from "@kunlun/shared-types";
import { describe, expect, it, vi } from "vitest";
import { PreciousMetalsService } from "./precious-metals.service";
import type {
  PreciousMetalsFeatureReadModel,
  PreciousMetalsMarketReadModel,
  PreciousMetalsPostgresReadModel,
} from "./precious-metals.types";

const NOW = "2026-08-27T07:00:00.000Z";

describe("PreciousMetalsService", () => {
  it("builds a point-in-time comparison with exact premium, ranking and provenance", async () => {
    const service = createService();
    const result = await service.terminal({});

    expect(result.executionCapability).toBe("REFERENCE_ONLY");
    expect(result.valuationPolicy).toBe("NAV_INAV_NON_EXECUTABLE");
    expect(result.status).toBe("PARTIAL");
    expect(result.funds[0]).toMatchObject({
      unifiedCode: "518880.SH",
      ranking: { rank: 1, metricValue: "900000000.00" },
      valuation: {
        referenceKind: "INAV",
        referenceValue: "1.000000",
        premiumDiscountBps: "200.00",
        freshness: "FRESH",
        referenceOnly: true,
      },
    });
    expect(result.gaps).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          scope: "MARKET",
          instrumentId: "161226.SZ",
          code: "NO_VISIBLE_DATA",
        }),
      ]),
    );
    expect(result.sourceVersions).toContain("provider-x@source-v1");
    expect(result.events[0]?.headline).toBe("贵金属避险需求升温");
  });

  it("keeps upstream source failures explicit instead of fabricating values", async () => {
    const market: PreciousMetalsMarketReadModel = {
      load: vi.fn().mockRejectedValue(new Error("clickhouse unavailable")),
    };
    const result = await createService({ market }).terminal({});

    expect(result.status).toBe("PARTIAL");
    expect(result.funds.every((fund) => fund.market === null)).toBe(true);
    expect(result.gaps).toContainEqual(
      expect.objectContaining({ scope: "MARKET", code: "SOURCE_UNAVAILABLE" }),
    );
  });

  it("fails the whole read model closed when fund identity storage is unavailable", async () => {
    const postgres: PreciousMetalsPostgresReadModel = {
      load: vi.fn().mockRejectedValue(new Error("postgres unavailable")),
    };
    const result = await createService({ postgres }).terminal({});

    expect(result.status).toBe("UNAVAILABLE");
    expect(result.funds).toEqual([]);
    expect(result.gaps[0]).toMatchObject({ severity: "ERROR", code: "SOURCE_UNAVAILABLE" });
  });

  it("rejects future-visible records returned by an incorrect repository", async () => {
    const postgres = basePostgres();
    postgres.load = vi.fn().mockResolvedValue({
      ...(await basePostgres().load(NOW)),
      funds: [
        {
          ...fundRecord(goldFund()),
          availableTime: "2026-08-28T00:00:00.000Z",
        },
      ],
    });
    await expect(createService({ postgres }).terminal({})).rejects.toThrow("future-visible record");
  });

  it("validates historical query boundaries", async () => {
    const service = createService();
    await expect(
      service.terminal({ mode: "HISTORICAL", asOf: "2026-08-28T00:00:00.000Z" }),
    ).rejects.toThrow("must not be in the future");
    await expect(service.terminal({ extra: "x" })).rejects.toThrow("unsupported query parameter");
  });
});

function createService(
  overrides: {
    postgres?: PreciousMetalsPostgresReadModel;
    market?: PreciousMetalsMarketReadModel;
    features?: PreciousMetalsFeatureReadModel;
  } = {},
): PreciousMetalsService {
  return new PreciousMetalsService(
    overrides.postgres ?? basePostgres(),
    overrides.market ?? baseMarket(),
    overrides.features ?? baseFeatures(),
    { canRead: async () => true },
    { now: () => new Date(NOW) },
  );
}

function basePostgres(): PreciousMetalsPostgresReadModel {
  return {
    load: vi.fn().mockResolvedValue({
      funds: [fundRecord(goldFund()), fundRecord(silverFund())],
      references: [
        reference("NAV", "518880.SH", "1.000000", "2026-08-27T01:00:00.000Z"),
        reference("INAV", "518880.SH", "1.000000", "2026-08-27T06:58:00.000Z"),
        reference("NAV", "161226.SZ", "7.000000", "2026-08-18T07:00:00.000Z"),
      ],
      events: [
        {
          eventId: "event-gold-1",
          instrumentIds: ["518880.SH"],
          eventType: "MACRO_POLICY",
          headline: "贵金属避险需求升温",
          summary: "公开信息显示避险主题热度上升。",
          publishTime: "2026-08-27T06:00:00.000Z",
          availableTime: "2026-08-27T06:01:00.000Z",
          processingTime: "2026-08-27T06:02:00.000Z",
          confidenceBps: 8200,
          modelVersion: "event-model-v1",
          sourceVersions: ["news@v1"],
          evidenceIds: ["evidence-event-1"],
        },
      ],
    }),
  };
}

function baseMarket(): PreciousMetalsMarketReadModel {
  return {
    load: vi.fn().mockResolvedValue([
      {
        instrumentId: "518880.SH",
        date: "2026-08-27",
        eventTime: "2026-08-27T06:57:00.000Z",
        close: "1.020000",
        volume: "880000000",
        amount: "900000000.00",
        suspended: false,
        dataVersion: "bars-v2",
        source: "market-provider",
        sourceVersion: "daily-v1",
        evidenceId: "evidence-market-gold",
        availableTime: "2026-08-27T06:58:00.000Z",
        processingTime: "2026-08-27T06:59:00.000Z",
      },
    ]),
  };
}

function baseFeatures(): PreciousMetalsFeatureReadModel {
  return {
    load: vi.fn().mockResolvedValue([
      {
        instrumentId: "518880.SH",
        featureName: "precious_metals_fund.liquidity_median_turnover_cny_20_sessions",
        featureVersion: "v1",
        algorithmVersion: "precious-metals-features-v1",
        valueType: "DECIMAL",
        value: "850000000.00",
        eventTime: "2026-08-27T06:00:00.000Z",
        availableTime: "2026-08-27T06:05:00.000Z",
        processingTime: "2026-08-27T06:06:00.000Z",
        evidenceId: "evidence-feature-gold",
      },
    ]),
  };
}

function fundRecord(data: PreciousMetalFund) {
  return {
    data,
    eventTime: "2026-08-20T00:00:00.000Z",
    availableTime: "2026-08-20T00:01:00.000Z",
    processingTime: "2026-08-20T00:02:00.000Z",
    sourceVersion: "source-v1",
    evidenceId: "evidence-metadata-" + data.unifiedCode,
  };
}

function reference(kind: "NAV" | "INAV", instrumentId: string, value: string, eventTime: string) {
  return {
    kind,
    instrumentId,
    referenceDate: eventTime.slice(0, 10),
    value,
    eventTime,
    availableTime: eventTime,
    processingTime: eventTime,
    source: "nav-provider",
    sourceVersion: "nav-v1",
    evidenceId: `evidence-${kind.toLowerCase()}-${instrumentId}`,
  };
}

function goldFund(): PreciousMetalFund {
  return fund("518880.SH", "SH", "ETF", "GOLD", "CNY", 0.95, "REVIEWED");
}

function silverFund(): PreciousMetalFund {
  return fund("161226.SZ", "SZ", "LOF", "SILVER", "USD", 0.9, "NEEDS_REVIEW");
}

function fund(
  unifiedCode: string,
  exchange: "SH" | "SZ",
  assetType: "ETF" | "LOF",
  underlyingCommodity: "GOLD" | "SILVER",
  navCurrency: string,
  confidence: number,
  reviewStatus: "REVIEWED" | "NEEDS_REVIEW",
): PreciousMetalFund {
  return {
    unifiedCode,
    exchange,
    assetType,
    fundAssetClass: "PRECIOUS_METALS",
    underlyingCommodity,
    tradingCurrency: "CNY",
    navCurrency,
    benchmarkOrTrackingIndex: underlyingCommodity + " benchmark",
    managementFeeRate: 0.005,
    validFrom: "2020-01-01",
    validTo: null,
    source: "provider-x",
    publishTime: "2026-08-20T00:00:00.000Z",
    ingestTime: "2026-08-20T00:00:30.000Z",
    availableTime: "2026-08-20T00:01:00.000Z",
    processingTime: "2026-08-20T00:02:00.000Z",
    rawObjectId: "raw-" + unifiedCode,
    confidence,
    reviewStatus,
  };
}
