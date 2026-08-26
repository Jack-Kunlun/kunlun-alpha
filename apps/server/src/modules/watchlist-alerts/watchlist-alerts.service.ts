import { createHash } from "node:crypto";
import {
  ConflictException,
  ForbiddenException,
  Inject,
  Injectable,
  NotFoundException,
} from "@nestjs/common";
import type { WatchlistAlertsWorkspace } from "@kunlun/shared-types";
import type { WatchlistAlertNotificationDispatcher } from "./watchlist-alerts.notification";
import type { WatchlistAlertsRepository } from "./watchlist-alerts.repository";
import {
  WATCHLIST_ALERTS_NOTIFICATION,
  WATCHLIST_ALERTS_OWNER_REF,
  WATCHLIST_ALERTS_REPOSITORY,
} from "./watchlist-alerts.tokens";
import type {
  AlertPreview,
  CreateWatchlistAlertRuleInput,
  EvaluateWatchlistAlertInput,
  NotificationEnvelope,
  StoredWatchlistAlertRule,
  WatchlistAlertHistory,
  WatchlistAlertOperator,
  WatchlistAlertRule,
} from "./watchlist-alerts.types";
import { parseCreateRule, parseEvaluation, parseToggleRule } from "./watchlist-alerts.validation";

const SUPPORTED_FIELDS = [
  "LAST_PRICE",
  "CHANGE_BPS",
  "EMOTION_SCORE_BPS",
  "FEATURE_VALUE",
] as const;
const SUPPORTED_OPERATORS = ["GT", "GTE", "LT", "LTE", "EQ"] as const;

@Injectable()
export class WatchlistAlertsService {
  constructor(
    @Inject(WATCHLIST_ALERTS_REPOSITORY)
    private readonly repository: WatchlistAlertsRepository,
    @Inject(WATCHLIST_ALERTS_NOTIFICATION)
    private readonly notifications: WatchlistAlertNotificationDispatcher,
    @Inject(WATCHLIST_ALERTS_OWNER_REF) private readonly configuredOwnerRef: string,
  ) {}

  async workspace(): Promise<WatchlistAlertsWorkspace> {
    const ownerRef = this.ownerRef();
    const [rules, history] = await Promise.all([
      this.repository.listLatestRules(ownerRef),
      this.repository.listHistory(ownerRef, 200),
    ]);
    return {
      schemaVersion: "watchlist-alerts-workspace-v1",
      ruleLanguage: "BOUNDED_COMPARISON_V1",
      generatedAt: new Date().toISOString(),
      rules: rules.map((item) => item.rule),
      history,
      supportedFields: [...SUPPORTED_FIELDS],
      supportedOperators: [...SUPPORTED_OPERATORS],
      dataMeaning: "RESEARCH_ALERTS_ONLY_NO_ORDER_PATH",
    };
  }

  async createRule(raw: unknown): Promise<WatchlistAlertsWorkspace> {
    const ownerRef = this.ownerRef();
    const input = parseCreateRule(raw);
    const commandHash = hash(stableStringify(input));
    const existing = await this.repository.findRuleByCommand(ownerRef, input.clientRequestId);
    if (existing) {
      if (existing.commandHash !== commandHash) {
        throw new ConflictException("clientRequestId was already used with different rule content");
      }
      return this.workspace();
    }

    const now = new Date().toISOString();
    const ruleId = hash(`watchlist-rule\u0000${ownerRef}\u0000${input.clientRequestId}`);
    const latest = await this.repository.findLatestRule(ownerRef, ruleId);
    const rule = this.buildRule(input, ruleId, latest, now);
    await this.repository.appendRule({
      ownerRef,
      commandRequestId: input.clientRequestId,
      commandHash,
      rule,
    });
    return this.workspace();
  }

  async toggleRule(ruleId: string, raw: unknown): Promise<WatchlistAlertsWorkspace> {
    const ownerRef = this.ownerRef();
    const input = parseToggleRule(raw);
    const commandHash = hash(stableStringify({ ruleId, ...input }));
    const existing = await this.repository.findRuleByCommand(ownerRef, input.clientRequestId);
    if (existing) {
      if (existing.commandHash !== commandHash) {
        throw new ConflictException(
          "clientRequestId was already used with different toggle content",
        );
      }
      return this.workspace();
    }
    const latest = await this.requireRule(ownerRef, ruleId);
    const now = new Date().toISOString();
    const revision = latest.rule.revision + 1;
    const revisionId = hash(
      stableStringify({
        ruleId,
        revision,
        enabled: input.enabled,
        previousRevisionId: latest.rule.revisionId,
        availableAt: now,
      }),
    );
    await this.repository.appendRule({
      ownerRef,
      commandRequestId: input.clientRequestId,
      commandHash,
      rule: {
        ...latest.rule,
        revisionId,
        revision,
        enabled: input.enabled,
        availableAt: now,
        previousRevisionId: latest.rule.revisionId,
      },
    });
    return this.workspace();
  }

  async preview(raw: unknown): Promise<AlertPreview> {
    const ownerRef = this.ownerRef();
    const input = parseEvaluation(raw);
    const rule = await this.requireRule(ownerRef, input.ruleId);
    return this.decide(ownerRef, rule.rule, input);
  }

  async evaluate(raw: unknown): Promise<WatchlistAlertsWorkspace> {
    const ownerRef = this.ownerRef();
    const input = parseEvaluation(raw);
    const now = new Date().toISOString();
    if (Date.parse(input.availableTime) > Date.parse(now)) {
      throw new ConflictException("availableTime cannot be in the future for persisted evaluation");
    }
    const stored = await this.requireRule(ownerRef, input.ruleId);
    const decision = await this.decide(ownerRef, stored.rule, input);
    const historyId = hash(
      `watchlist-history\u0000${stored.rule.ruleId}\u0000${stored.rule.revisionId}\u0000${input.eventId}`,
    );
    const notificationId =
      decision.outcome === "TRIGGERED" ? hash(`notification\u0000${historyId}`) : null;
    const history: WatchlistAlertHistory = {
      schemaVersion: "watchlist-alert-history-v1",
      historyId,
      ruleId: stored.rule.ruleId,
      revisionId: stored.rule.revisionId,
      eventId: input.eventId,
      instrumentId: input.instrumentId,
      eventTime: input.eventTime,
      availableTime: input.availableTime,
      outcome: decision.outcome,
      observedValue: input.observedValue,
      notificationId,
      notificationStatus: notificationId ? "PENDING" : "NONE",
      detail: decision.detail,
      createdAt: now,
    };
    const notification = notificationId
      ? this.notification(ownerRef, stored.rule, history, notificationId)
      : null;
    const appended = await this.repository.appendHistory(ownerRef, history, notification);
    if (!appended.duplicate && notification) await this.deliver(ownerRef, notification);
    return this.workspace();
  }

  private buildRule(
    input: CreateWatchlistAlertRuleInput,
    ruleId: string,
    latest: StoredWatchlistAlertRule | null,
    now: string,
  ): WatchlistAlertRule {
    const revision = (latest?.rule.revision ?? 0) + 1;
    const revisionId = hash(
      stableStringify({
        ruleId,
        revision,
        name: input.name,
        enabled: input.enabled,
        instrumentIds: input.instrumentIds,
        condition: input.condition,
        quietPeriod: input.quietPeriod,
        throttleSeconds: input.throttleSeconds,
        availableAt: now,
      }),
    );
    return {
      schemaVersion: "watchlist-alert-rule-v1",
      ruleId,
      revisionId,
      revision,
      name: input.name,
      enabled: input.enabled,
      instrumentIds: input.instrumentIds,
      condition: input.condition,
      quietPeriod: input.quietPeriod,
      throttleSeconds: input.throttleSeconds,
      notificationChannel: "IN_APP",
      createdAt: latest?.rule.createdAt ?? now,
      availableAt: now,
      previousRevisionId: latest?.rule.revisionId ?? null,
    };
  }

  private async decide(
    ownerRef: string,
    rule: WatchlistAlertRule,
    input: EvaluateWatchlistAlertInput,
  ): Promise<AlertPreview> {
    if (!rule.enabled) return { outcome: "RULE_DISABLED", detail: "规则已停用，未发送通知" };
    if (!rule.instrumentIds.includes(input.instrumentId)) {
      return { outcome: "CONDITION_NOT_MET", detail: "事件证券不在规则自选范围内" };
    }
    if (rule.condition.field !== input.field || rule.condition.featureName !== input.featureName) {
      return { outcome: "CONDITION_NOT_MET", detail: "事件指标与规则指标不匹配" };
    }
    if (rule.quietPeriod && isQuiet(input.availableTime, rule.quietPeriod)) {
      return { outcome: "QUIET_PERIOD", detail: "当前处于免打扰时段" };
    }
    const lastTriggered = await this.repository.findLatestTriggeredTime(
      ownerRef,
      rule.ruleId,
      input.availableTime,
    );
    if (
      lastTriggered &&
      Date.parse(input.availableTime) - Date.parse(lastTriggered) < rule.throttleSeconds * 1000
    ) {
      return { outcome: "THROTTLED", detail: "相同规则仍在通知节流窗口内" };
    }
    if (!compareDecimal(input.observedValue, rule.condition.threshold, rule.condition.operator)) {
      return { outcome: "CONDITION_NOT_MET", detail: "当前值尚未达到规则阈值" };
    }
    return { outcome: "TRIGGERED", detail: "条件已满足，站内通知已进入可靠投递流程" };
  }

  private notification(
    ownerRef: string,
    rule: WatchlistAlertRule,
    history: WatchlistAlertHistory,
    notificationId: string,
  ): NotificationEnvelope {
    return {
      notificationId,
      historyId: history.historyId,
      ownerRef,
      title: rule.name,
      body: `${history.instrumentId} ${rule.condition.field} ${rule.condition.operator} ${rule.condition.threshold}`,
      availableAt: history.availableTime,
    };
  }

  private async deliver(ownerRef: string, notification: NotificationEnvelope): Promise<void> {
    const updatedAt = new Date().toISOString();
    try {
      await this.notifications.deliver(notification);
      await this.repository.markNotification(
        ownerRef,
        notification.notificationId,
        "DELIVERED",
        null,
        updatedAt,
      );
    } catch (error) {
      const message = error instanceof Error ? error.message.slice(0, 240) : "notification failed";
      await this.repository.markNotification(
        ownerRef,
        notification.notificationId,
        "FAILED",
        message,
        updatedAt,
      );
    }
  }

  private ownerRef(): string {
    const ownerRef = this.configuredOwnerRef.trim();
    if (!ownerRef) throw new ForbiddenException("watchlist alerts owner is not configured");
    return ownerRef;
  }

  private async requireRule(ownerRef: string, ruleId: string): Promise<StoredWatchlistAlertRule> {
    const rule = await this.repository.findLatestRule(ownerRef, ruleId);
    if (!rule) throw new NotFoundException("watchlist alert rule not found");
    return rule;
  }
}

function isQuiet(
  availableTime: string,
  quietPeriod: NonNullable<WatchlistAlertRule["quietPeriod"]>,
): boolean {
  const shanghai = new Date(Date.parse(availableTime) + 8 * 60 * 60 * 1000);
  const minute = shanghai.getUTCHours() * 60 + shanghai.getUTCMinutes();
  if (quietPeriod.startMinute < quietPeriod.endMinute) {
    return minute >= quietPeriod.startMinute && minute < quietPeriod.endMinute;
  }
  return minute >= quietPeriod.startMinute || minute < quietPeriod.endMinute;
}

function compareDecimal(left: string, right: string, operator: WatchlistAlertOperator): boolean {
  const comparison = decimalCompare(left, right);
  if (operator === "GT") return comparison > 0;
  if (operator === "GTE") return comparison >= 0;
  if (operator === "LT") return comparison < 0;
  if (operator === "LTE") return comparison <= 0;
  return comparison === 0;
}

function decimalCompare(left: string, right: string): number {
  const a = decimalParts(left);
  const b = decimalParts(right);
  const scale = Math.max(a.scale, b.scale);
  const leftValue = a.value * 10n ** BigInt(scale - a.scale);
  const rightValue = b.value * 10n ** BigInt(scale - b.scale);
  return leftValue < rightValue ? -1 : leftValue > rightValue ? 1 : 0;
}

function decimalParts(value: string): { value: bigint; scale: number } {
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [whole = "0", fraction = ""] = unsigned.split(".");
  const integer = BigInt(`${whole}${fraction}`);
  return { value: negative ? -integer : integer, scale: fraction.length };
}

function hash(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([left], [right]) =>
      left.localeCompare(right),
    );
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${stableStringify(item)}`).join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}
