import { BadRequestException } from "@nestjs/common";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { InMemoryWatchlistAlertsRepository } from "./in-memory-watchlist-alerts.repository";
import type { WatchlistAlertNotificationDispatcher } from "./watchlist-alerts.notification";
import { WatchlistAlertsService } from "./watchlist-alerts.service";

const NOW = "2026-08-26T02:00:00.000Z";

describe("WatchlistAlertsService", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(NOW));
  });

  afterEach(() => vi.useRealTimers());

  it("deduplicates a repeated event and delivers one in-app notification", async () => {
    const deliver = vi.fn().mockResolvedValue(undefined);
    const service = createService({ deliver });
    const ruleId = await createRule(service);
    const event = evaluation(ruleId, "event-1", "2026-08-26T01:59:00.000Z");

    await service.evaluate(event);
    const workspace = await service.evaluate(event);

    expect(workspace.history).toHaveLength(1);
    expect(workspace.history[0]).toMatchObject({
      outcome: "TRIGGERED",
      notificationStatus: "DELIVERED",
    });
    expect(deliver).toHaveBeenCalledTimes(1);
  });

  it("handles a quiet period that crosses midnight in Asia/Shanghai", async () => {
    const service = createService({ deliver: vi.fn().mockResolvedValue(undefined) });
    const ruleId = await createRule(service, {
      quietPeriod: { timezone: "Asia/Shanghai", startMinute: 23 * 60, endMinute: 7 * 60 },
    });

    const workspace = await service.evaluate(
      evaluation(ruleId, "quiet-event", "2026-08-25T16:30:00.000Z"),
    );

    expect(workspace.history[0]?.outcome).toBe("QUIET_PERIOD");
    expect(workspace.history[0]?.notificationStatus).toBe("NONE");
  });

  it("records disabled rules without evaluating or notifying", async () => {
    const deliver = vi.fn().mockResolvedValue(undefined);
    const service = createService({ deliver });
    const ruleId = await createRule(service, { enabled: false });

    const workspace = await service.evaluate(
      evaluation(ruleId, "disabled-event", "2026-08-26T01:58:00.000Z"),
    );

    expect(workspace.history[0]?.outcome).toBe("RULE_DISABLED");
    expect(deliver).not.toHaveBeenCalled();
  });

  it("retains a failed delivery outcome and rejects unbounded rule input", async () => {
    const service = createService({
      deliver: vi.fn().mockRejectedValue(new Error("outbox offline")),
    });
    const ruleId = await createRule(service);
    const workspace = await service.evaluate(
      evaluation(ruleId, "failed-event", "2026-08-26T01:57:00.000Z"),
    );

    expect(workspace.history[0]?.notificationStatus).toBe("FAILED");
    await expect(
      service.createRule({ ...createRuleBody(), expression: "process.exit()" }),
    ).rejects.toBeInstanceOf(BadRequestException);
  });
});

function createService(dispatcher: WatchlistAlertNotificationDispatcher) {
  return new WatchlistAlertsService(
    new InMemoryWatchlistAlertsRepository(),
    dispatcher,
    "local-research-user",
  );
}

async function createRule(
  service: WatchlistAlertsService,
  overrides: Record<string, unknown> = {},
): Promise<string> {
  const workspace = await service.createRule({ ...createRuleBody(), ...overrides });
  const ruleId = workspace.rules[0]?.ruleId;
  if (!ruleId) throw new Error("expected created rule");
  return ruleId;
}

function createRuleBody() {
  return {
    clientRequestId: "create-price-rule",
    name: "贵州茅台价格提醒",
    enabled: true,
    instrumentIds: ["600519.SH"],
    condition: {
      field: "LAST_PRICE",
      operator: "GTE",
      threshold: "1500.00",
      featureName: null,
    },
    quietPeriod: null,
    throttleSeconds: 300,
    notificationChannel: "IN_APP",
  };
}

function evaluation(ruleId: string, eventId: string, availableTime: string) {
  return {
    ruleId,
    eventId,
    instrumentId: "600519.SH",
    field: "LAST_PRICE",
    featureName: null,
    observedValue: "1500.00000001",
    eventTime: availableTime,
    availableTime,
  };
}
