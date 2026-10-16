import type { InstrumentBarsResponse } from "@kunlun/shared-types";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { InstrumentBarsService } from "../instrument-intelligence/instrument-bars.service";
import type { InstrumentIntelligenceAuthorizer } from "../instrument-intelligence/instrument-intelligence.service";
import type { InstrumentBarsReadModel } from "../instrument-intelligence/read-model.types";
import { InMemoryWatchlistAlertsRepository } from "./in-memory-watchlist-alerts.repository";
import type { WatchlistAlertNotificationDispatcher } from "./watchlist-alerts.notification";
import { WatchlistAlertsEvaluationRunner } from "./watchlist-alerts.evaluation-runner";
import { WatchlistAlertsService } from "./watchlist-alerts.service";

const NOW = "2026-08-26T08:02:00.000Z";

describe("WatchlistAlertsEvaluationRunner", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(NOW));
  });

  afterEach(() => vi.useRealTimers());

  it("evaluates latest price and change once per immutable bar evidence", async () => {
    const service = createService();
    await createRule(service, "latest-price", "LAST_PRICE", "10.50");
    await createRule(service, "daily-change", "CHANGE_BPS", "900");
    await createRule(service, "feature-rule", "FEATURE_VALUE", "0.50");
    const bars = vi.fn().mockResolvedValue(barsResponse());
    const runner = new WatchlistAlertsEvaluationRunner(service, { bars }, 0);

    const first = await runner.runOnce();
    const second = await runner.runOnce();
    const workspace = await service.workspace();

    expect(first).toMatchObject({ evaluated: 2, skippedUnsupported: 1, failed: 0 });
    expect(second).toMatchObject({ evaluated: 2, skippedUnsupported: 1, failed: 0 });
    expect(bars).toHaveBeenCalledTimes(2);
    expect(workspace.history).toHaveLength(2);
    expect(workspace.history.map((item) => item.observedValue).sort()).toEqual(["1000", "11.00"]);
    expect(workspace.history.every((item) => item.outcome === "TRIGGERED")).toBe(true);
  });

  it("uses the real bars query parser and keeps retries idempotent", async () => {
    const dispatcher: WatchlistAlertNotificationDispatcher = {
      deliver: vi.fn().mockResolvedValue(undefined),
    };
    const service = createService(dispatcher);
    await createRule(service, "latest-price", "LAST_PRICE", "10.50");
    await createRule(service, "daily-change", "CHANGE_BPS", "900");

    const repository: InstrumentBarsReadModel = {
      load: vi.fn().mockResolvedValue(barsResponse().bars),
    };
    const authorizer: InstrumentIntelligenceAuthorizer = {
      canRead: vi.fn().mockResolvedValue(true),
    };
    const clock = { now: vi.fn(() => new Date(NOW)) };
    const instrumentBars = new InstrumentBarsService(repository, authorizer, clock);
    const runner = new WatchlistAlertsEvaluationRunner(service, instrumentBars, 0);

    const first = await runner.runOnce();
    const second = await runner.runOnce();
    const workspace = await service.workspace();

    expect(first).toMatchObject({ evaluated: 2, failed: 0 });
    expect(second).toMatchObject({ evaluated: 2, failed: 0 });
    expect(repository.load).toHaveBeenCalledTimes(2);
    expect(repository.load).toHaveBeenNthCalledWith(1, "600519.SH", NOW, 2);
    expect(authorizer.canRead).toHaveBeenCalledTimes(2);
    expect(workspace.history).toHaveLength(2);
    expect(dispatcher.deliver).toHaveBeenCalledTimes(2);
  });
});

function createService(
  dispatcher: WatchlistAlertNotificationDispatcher = {
    deliver: vi.fn().mockResolvedValue(undefined),
  },
): WatchlistAlertsService {
  return new WatchlistAlertsService(
    new InMemoryWatchlistAlertsRepository(),
    dispatcher,
    "local-research-user",
  );
}

async function createRule(
  service: WatchlistAlertsService,
  clientRequestId: string,
  field: "LAST_PRICE" | "CHANGE_BPS" | "FEATURE_VALUE",
  threshold: string,
): Promise<void> {
  await service.createRule({
    clientRequestId,
    name: clientRequestId,
    enabled: true,
    instrumentIds: ["600519.SH"],
    condition: {
      field,
      operator: "GTE",
      threshold,
      featureName: field === "FEATURE_VALUE" ? "momentum_10d" : null,
    },
    quietPeriod: null,
    throttleSeconds: 0,
    notificationChannel: "IN_APP",
  });
}

function barsResponse(): InstrumentBarsResponse {
  return {
    schemaVersion: "instrument-bars-v1",
    dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
    instrumentId: "600519.SH",
    mode: "CURRENT",
    requestedAsOf: NOW,
    effectiveAsOf: NOW,
    interval: "DAILY",
    priceType: "RAW",
    status: "AVAILABLE",
    barCount: 2,
    dataCutoffTime: "2026-08-26T07:00:00.000Z",
    freshnessSeconds: 3720,
    sourceVersions: ["akshare-eastmoney@2026.08.26"],
    evidenceIds: ["evidence-previous", "evidence-latest"],
    bars: [
      bar("2026-08-25", "10.00", "evidence-previous"),
      bar("2026-08-26", "11.00", "evidence-latest"),
    ],
  };
}

function bar(date: string, close: string, evidenceId: string) {
  return {
    date,
    eventTime: `${date}T07:00:00.000Z`,
    open: close,
    high: close,
    low: close,
    close,
    volume: "100",
    amount: "1000",
    suspended: false,
    dataVersion: "bars-v2",
    source: "akshare-eastmoney",
    sourceVersion: "2026.08.26",
    evidenceId,
    availableTime: `${date}T08:00:00.000Z`,
    processingTime: `${date}T08:01:00.000Z`,
  };
}
