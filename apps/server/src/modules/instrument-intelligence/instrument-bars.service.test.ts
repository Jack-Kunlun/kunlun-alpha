import { ForbiddenException } from "@nestjs/common";
import { describe, expect, it } from "vitest";
import type { InstrumentDailyBar, InstrumentBarsReadModel } from "./read-model.types";
import {
  AllowAllInstrumentIntelligenceAuthorizer,
  InstrumentBarsService,
} from "./instrument-bars.service";

const cutoff = "2026-08-25T08:00:00.000Z";
const bar: InstrumentDailyBar = {
  date: "2026-08-25",
  eventTime: "2026-08-25T07:00:00.000Z",
  open: "10.0000",
  high: "11.0000",
  low: "9.0000",
  close: "10.5000",
  volume: "9007199254740993",
  amount: "9007199254740993.25",
  suspended: false,
  dataVersion: "bars-v2",
  source: "tushare-pro",
  sourceVersion: "tushare-v1",
  evidenceId: "evidence-1",
  availableTime: "2026-08-25T07:01:00.000Z",
  processingTime: "2026-08-25T07:02:00.000Z",
};

describe("InstrumentBarsService", () => {
  it("returns versioned metadata, aggregate provenance and ascending bars", async () => {
    const repository: InstrumentBarsReadModel = { load: async () => [bar] };
    const service = new InstrumentBarsService(
      repository,
      new AllowAllInstrumentIntelligenceAuthorizer(),
      { now: () => new Date(cutoff) },
    );

    await expect(service.bars("600519.SH", {})).resolves.toMatchObject({
      schemaVersion: "instrument-bars-v1",
      dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
      instrumentId: "600519.SH",
      interval: "DAILY",
      priceType: "RAW",
      status: "AVAILABLE",
      barCount: 1,
      bars: [bar],
      sourceVersions: ["tushare-pro@tushare-v1"],
      evidenceIds: ["evidence-1"],
    });
  });

  it("reports an empty PIT result without latest fallback", async () => {
    const service = new InstrumentBarsService(
      { load: async () => [] },
      new AllowAllInstrumentIntelligenceAuthorizer(),
      { now: () => new Date(cutoff) },
    );
    await expect(service.bars("600519.SH", {})).resolves.toMatchObject({
      status: "EMPTY",
      barCount: 0,
      bars: [],
      sourceVersions: [],
      evidenceIds: [],
      freshnessSeconds: null,
    });
  });

  it("rejects a repository bar that violates the requested PIT", async () => {
    const service = new InstrumentBarsService(
      {
        load: async () => [{ ...bar, processingTime: "2026-08-25T08:00:01.000Z" }],
      },
      new AllowAllInstrumentIntelligenceAuthorizer(),
      { now: () => new Date(cutoff) },
    );
    await expect(service.bars("600519.SH", {})).rejects.toThrow("future-visible");
  });

  it("fails closed when the reader is forbidden", async () => {
    const service = new InstrumentBarsService(
      { load: async () => [] },
      { canRead: async () => false },
      { now: () => new Date(cutoff) },
    );
    await expect(service.bars("600519.SH", {})).rejects.toBeInstanceOf(ForbiddenException);
  });
});
