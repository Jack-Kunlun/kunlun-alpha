import { describe, expect, it } from "vitest";
import type {
  InstrumentEmotionReadModel,
  InstrumentFeatureReadModel,
  InstrumentMarketReadModel,
  PostgresInstrumentContextReadModel,
} from "./read-model.types";
import {
  AllowAllInstrumentIntelligenceAuthorizer,
  InstrumentIntelligenceService,
} from "./instrument-intelligence.service";

const cutoff = "2026-08-25T08:00:00.000Z";
const emptyPostgres: PostgresInstrumentContextReadModel = {
  async load() {
    return { identity: null, sectors: [], events: [], seats: [], claims: [], evidence: [] };
  },
};
const _emptyMarket: InstrumentMarketReadModel = {
  async load() {
    return null;
  },
};
const emptyEmotion: InstrumentEmotionReadModel = {
  async load() {
    return null;
  },
};
const emptyFeatures: InstrumentFeatureReadModel = {
  async load() {
    return [];
  },
};

describe("InstrumentIntelligenceService", () => {
  it("passes one effectiveAsOf to every store and reports cross-store semantics", async () => {
    const observed: string[] = [];
    const postgres: PostgresInstrumentContextReadModel = {
      async load(_instrumentId, asOf) {
        observed.push(asOf);
        return { identity: null, sectors: [], events: [], seats: [], claims: [], evidence: [] };
      },
    };
    const market: InstrumentMarketReadModel = {
      async load(_instrumentId, asOf) {
        observed.push(asOf);
        return null;
      },
    };
    const emotion: InstrumentEmotionReadModel = {
      async load(asOf) {
        observed.push(asOf);
        return null;
      },
    };
    const features: InstrumentFeatureReadModel = {
      async load(_instrumentId, asOf) {
        observed.push(asOf);
        return [];
      },
    };
    const service = new InstrumentIntelligenceService(
      postgres,
      market,
      emotion,
      features,
      new AllowAllInstrumentIntelligenceAuthorizer(),
      { now: () => new Date(cutoff) },
    );

    const response = await service.detail("600519.SH", {});

    expect(new Set(observed)).toEqual(new Set([cutoff]));
    expect(response.snapshotBoundary.consistency).toBe("BEST_EFFORT_CROSS_STORE");
    expect(response.sections.identity.status).toBe("EMPTY");
    expect(response.dataMeaning).toBe("RESEARCH_ONLY_NO_REAL_ORDER_PATH");
  });

  it("isolates a ClickHouse section failure without falling back to latest", async () => {
    const service = new InstrumentIntelligenceService(
      emptyPostgres,
      {
        async load() {
          throw new Error("clickhouse unavailable");
        },
      },
      emptyEmotion,
      emptyFeatures,
      new AllowAllInstrumentIntelligenceAuthorizer(),
      { now: () => new Date(cutoff) },
    );

    const response = await service.detail("600519.SH", {});

    expect(response.sections.market.status).toBe("UNAVAILABLE");
    expect(response.sections.market.unavailableReason).toBe(
      "CLICKHOUSE_MARKET_QUERY_FAILED",
    );
    expect(response.sections.emotion.status).toBe("EMPTY");
  });

  it("rejects a repository result visible only after the requested history point", async () => {
    const futureMarket: InstrumentMarketReadModel = {
      async load() {
        return {
          date: "2026-08-25",
          eventTime: cutoff,
          open: "1",
          high: "1",
          low: "1",
          close: "1",
          volume: "1",
          amount: "1",
          suspended: false,
          dataVersion: "v1",
          source: "test",
          sourceVersion: "v1",
          evidenceId: "e1",
          availableTime: "2026-08-25T08:00:01.000Z",
          processingTime: "2026-08-25T08:00:01.000Z",
        };
      },
    };
    const service = new InstrumentIntelligenceService(
      emptyPostgres,
      futureMarket,
      emptyEmotion,
      emptyFeatures,
      new AllowAllInstrumentIntelligenceAuthorizer(),
      { now: () => new Date(cutoff) },
    );

    await expect(service.detail("600519.SH", {})).rejects.toThrow("future-visible");
  });
});
