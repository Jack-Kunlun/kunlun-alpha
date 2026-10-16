import { BadRequestException, ConflictException, NotFoundException } from "@nestjs/common";
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

  it("fails closed when an event identity is reused with different observations", async () => {
    const service = createService({ deliver: vi.fn().mockResolvedValue(undefined) });
    const ruleId = await createRule(service);
    const first = evaluation(ruleId, "conflicting-event", "2026-08-26T01:59:00.000Z");
    await service.evaluate(first);

    await expect(service.evaluate({ ...first, observedValue: "1600.00" })).rejects.toBeInstanceOf(
      ConflictException,
    );
    expect((await service.workspace()).history).toHaveLength(1);
  });

  it("keeps delivered notifications across service restarts and records an idempotent read receipt", async () => {
    const repository = new InMemoryWatchlistAlertsRepository();
    const deliver = vi.fn().mockResolvedValue(undefined);
    const service = new WatchlistAlertsService(repository, { deliver }, "local-research-user");
    const ruleId = await createRule(service);
    await service.evaluate(evaluation(ruleId, "persistent-event", "2026-08-26T01:59:00.000Z"));

    const restarted = new WatchlistAlertsService(repository, { deliver }, "local-research-user");
    const before = await restarted.notificationCenter();
    const notificationId = before.notifications[0]?.notificationId;

    expect(before).toMatchObject({
      schemaVersion: "in-app-notification-center-v1",
      unreadCount: 1,
      dataMeaning: "RESEARCH_IN_APP_ALERTS_NO_ORDER_PATH",
      notifications: [
        {
          instrumentId: "600519.SH",
          deliveryStatus: "DELIVERED",
          deliveryAttempts: 1,
          readAt: null,
        },
      ],
    });
    expect(notificationId).toBeTypeOf("string");
    if (!notificationId) throw new Error("expected notification id");

    const firstRead = await restarted.readNotification(notificationId);
    const firstReadAt = firstRead.notifications[0]?.readAt;
    vi.setSystemTime(new Date("2026-08-26T02:05:00.000Z"));
    const repeatedRead = await restarted.readNotification(notificationId);

    expect(firstRead.unreadCount).toBe(0);
    expect(firstReadAt).toBe(NOW);
    expect(repeatedRead.notifications[0]?.readAt).toBe(firstReadAt);
    await expect(restarted.readNotification("f".repeat(64))).rejects.toBeInstanceOf(
      NotFoundException,
    );

    const otherOwner = new WatchlistAlertsService(repository, { deliver }, "another-owner");
    expect((await otherOwner.notificationCenter()).notifications).toEqual([]);
    await expect(otherOwner.readNotification(notificationId)).rejects.toBeInstanceOf(
      NotFoundException,
    );
  });

  it("marks every persisted notification read without deleting delivery evidence", async () => {
    const service = createService({ deliver: vi.fn().mockResolvedValue(undefined) });
    const ruleId = await createRule(service, { throttleSeconds: 0 });
    await service.evaluate(evaluation(ruleId, "event-one", "2026-08-26T01:58:00.000Z"));
    await service.evaluate(evaluation(ruleId, "event-two", "2026-08-26T01:59:00.000Z"));

    expect((await service.notificationCenter()).unreadCount).toBe(2);
    const after = await service.readAllNotifications();

    expect(after.unreadCount).toBe(0);
    expect(after.notifications).toHaveLength(2);
    expect(after.notifications.every((item) => item.readAt === NOW)).toBe(true);
    expect((await service.workspace()).history).toHaveLength(2);
  });

  it("appends a name and threshold edit without rewriting legacy rule fields or history", async () => {
    const repository = new InMemoryWatchlistAlertsRepository();
    const dispatcher = { deliver: vi.fn().mockResolvedValue(undefined) };
    const service = new WatchlistAlertsService(repository, dispatcher, "local-research-user");
    const ruleId = await createRule(service, {
      name: "动量提醒",
      enabled: false,
      condition: {
        field: "FEATURE_VALUE",
        operator: "GTE",
        threshold: "0.50",
        featureName: "momentum_20d",
      },
      quietPeriod: { timezone: "Asia/Shanghai", startMinute: 60, endMinute: 120 },
      throttleSeconds: 60,
    });
    await service.evaluate({
      ...evaluation(ruleId, "legacy-rule-event", "2026-08-26T01:59:00.000Z"),
      field: "FEATURE_VALUE",
      featureName: "momentum_20d",
      observedValue: "0.75",
    });
    const before = await service.workspace();
    const original = before.rules[0];
    if (!original) throw new Error("expected initial rule revision");

    const edited = await service.updateRule(ruleId, {
      clientRequestId: "edit-legacy-rule",
      expectedRevision: 1,
      name: "动量阈值提醒",
      threshold: "0.80",
    });
    const latest = edited.rules[0];
    if (!latest) throw new Error("expected edited rule revision");

    expect(latest).toMatchObject({
      ruleId,
      revision: 2,
      name: "动量阈值提醒",
      enabled: false,
      instrumentIds: ["600519.SH"],
      condition: {
        field: "FEATURE_VALUE",
        operator: "GTE",
        threshold: "0.80",
        featureName: "momentum_20d",
      },
      quietPeriod: { timezone: "Asia/Shanghai", startMinute: 60, endMinute: 120 },
      throttleSeconds: 60,
      notificationChannel: "IN_APP",
      createdAt: original.createdAt,
      previousRevisionId: original.revisionId,
    });
    expect(edited.history).toHaveLength(1);
    expect(edited.history[0]).toMatchObject({ revisionId: original.revisionId });

    const restarted = new WatchlistAlertsService(repository, dispatcher, "local-research-user");
    expect(await restarted.workspace()).toMatchObject({
      rules: [latest],
      history: [{ revisionId: original.revisionId, eventId: "legacy-rule-event" }],
    });
  });

  it("makes edit retries idempotent and rejects reused command IDs with different content or path", async () => {
    const repository = new InMemoryWatchlistAlertsRepository();
    const dispatcher = { deliver: vi.fn().mockResolvedValue(undefined) };
    const service = new WatchlistAlertsService(repository, dispatcher, "local-research-user");
    const firstRuleId = await createRule(service);
    await service.createRule({
      ...createRuleBody(),
      clientRequestId: "create-second-rule",
      name: "第二条提醒",
    });
    const secondRuleId = (await service.workspace()).rules.find(
      (item) => item.name === "第二条提醒",
    )?.ruleId;
    if (!secondRuleId) throw new Error("expected second rule");

    const command = {
      clientRequestId: "single-edit-command",
      expectedRevision: 1,
      name: "修订后的提醒",
      threshold: "1600.00",
    };
    const first = await service.updateRule(firstRuleId, command);
    const retry = await service.updateRule(firstRuleId, command);
    expect(retry.rules.find((item) => item.ruleId === firstRuleId)?.revision).toBe(2);
    expect(first.rules.find((item) => item.ruleId === firstRuleId)?.revision).toBe(2);
    await service.toggleRule(firstRuleId, {
      clientRequestId: "later-toggle-after-edit",
      enabled: false,
    });
    const lateRetry = await service.updateRule(firstRuleId, command);
    expect(lateRetry.rules.find((item) => item.ruleId === firstRuleId)?.revision).toBe(3);

    await expect(
      service.updateRule(firstRuleId, { ...command, threshold: "1700.00" }),
    ).rejects.toBeInstanceOf(ConflictException);
    await expect(
      service.updateRule(secondRuleId, { ...command, expectedRevision: 1 }),
    ).rejects.toBeInstanceOf(ConflictException);
    expect(
      (await service.workspace()).rules.find((item) => item.ruleId === firstRuleId)?.revision,
    ).toBe(3);
  });

  it("allows only one concurrent edit or toggle from the same expected revision", async () => {
    const service = createService({ deliver: vi.fn().mockResolvedValue(undefined) });
    const ruleId = await createRule(service);

    const results = await Promise.allSettled([
      service.updateRule(ruleId, {
        clientRequestId: "racing-edit",
        expectedRevision: 1,
        name: "并发修改",
        threshold: "1550.00",
      }),
      service.toggleRule(ruleId, { clientRequestId: "racing-toggle", enabled: false }),
    ]);

    expect(results.filter((result) => result.status === "fulfilled")).toHaveLength(1);
    const rejected = results.find((result) => result.status === "rejected");
    expect(rejected?.status).toBe("rejected");
    if (rejected?.status === "rejected") {
      expect(rejected.reason).toBeInstanceOf(ConflictException);
    }
    expect((await service.workspace()).rules[0]?.revision).toBe(2);
  });

  it("deduplicates simultaneous identical rule creation commands", async () => {
    const service = createService({ deliver: vi.fn().mockResolvedValue(undefined) });

    const workspaces = await Promise.all([
      service.createRule(createRuleBody()),
      service.createRule(createRuleBody()),
    ]);

    expect(workspaces.map((workspace) => workspace.rules[0]?.revision)).toEqual([1, 1]);
    expect((await service.workspace()).rules).toHaveLength(1);
  });

  it("deduplicates concurrent identical edits and validates owner, revision, and decimal bounds", async () => {
    const repository = new InMemoryWatchlistAlertsRepository();
    const dispatcher = { deliver: vi.fn().mockResolvedValue(undefined) };
    const service = new WatchlistAlertsService(repository, dispatcher, "local-research-user");
    const ruleId = await createRule(service);
    const command = {
      clientRequestId: "concurrent-edit-retry",
      expectedRevision: 1,
      name: "并发重试提醒",
      threshold: "1550.25",
    };

    const retries = await Promise.all([
      service.updateRule(ruleId, command),
      service.updateRule(ruleId, command),
    ]);
    expect(retries.map((result) => result.rules[0]?.revision)).toEqual([2, 2]);

    await expect(
      service.updateRule(ruleId, { ...command, clientRequestId: "stale-edit" }),
    ).rejects.toBeInstanceOf(ConflictException);
    await expect(
      service.updateRule("f".repeat(64), {
        ...command,
        clientRequestId: "unknown-rule-edit",
      }),
    ).rejects.toBeInstanceOf(NotFoundException);
    const otherOwner = new WatchlistAlertsService(repository, dispatcher, "another-owner");
    await expect(otherOwner.updateRule(ruleId, command)).rejects.toBeInstanceOf(NotFoundException);
    await expect(
      service.updateRule(ruleId, {
        ...command,
        clientRequestId: "unsafe-revision",
        expectedRevision: Number.MAX_SAFE_INTEGER + 1,
      }),
    ).rejects.toBeInstanceOf(BadRequestException);
    await expect(
      service.updateRule(ruleId, {
        ...command,
        clientRequestId: "invalid-decimal",
        threshold: "1.234567891",
      }),
    ).rejects.toBeInstanceOf(BadRequestException);
    await expect(
      service.updateRule(ruleId, {
        ...command,
        clientRequestId: "unknown-body-field",
        unexpected: true,
      }),
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
