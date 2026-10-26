import type { WatchlistAlertHistory } from "@kunlun/shared-types";
import { z } from "zod";
import { isCanonicalInstrumentId } from "@/features/instrument/use-instrument-intelligence";

export const ALERT_HISTORY_OUTCOMES: Record<WatchlistAlertHistory["outcome"], string> = {
  TRIGGERED: "已触发",
  CONDITION_NOT_MET: "未达条件",
  THROTTLED: "节流中",
  QUIET_PERIOD: "免打扰",
  RULE_DISABLED: "已停用",
};
export const ALERT_HISTORY_DELIVERY: Record<WatchlistAlertHistory["notificationStatus"], string> = {
  NONE: "无通知",
  PENDING: "待投递",
  DELIVERED: "已投递",
  FAILED: "投递失败",
};
export interface AlertHistoryModel {
  generatedAt: string;
  rows: WatchlistAlertHistory[];
}
export interface AlertHistoryFilters {
  query: string;
  outcome: "ALL" | WatchlistAlertHistory["outcome"];
  delivery: "ALL" | WatchlistAlertHistory["notificationStatus"];
}
const instantSchema = z.iso.datetime({ offset: true });
function fail(): never {
  throw new Error("评估历史数据不可用，请刷新后核对。");
}
function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail();
  return value as Record<string, unknown>;
}
function text(value: unknown, maximum = Infinity): string {
  if (typeof value !== "string" || value.trim().length === 0 || value.length > maximum) fail();
  return value;
}
function digest(value: unknown): string {
  if (typeof value !== "string" || !/^[a-f0-9]{64}$/.test(value)) fail();
  return value;
}
function choice<T extends string>(value: unknown, choices: Record<T, string>): T {
  if (typeof value !== "string" || !Object.hasOwn(choices, value)) fail();
  return value as T;
}
function instant(value: unknown): bigint {
  if (typeof value !== "string") fail();
  const time = value.replace("t", "T").replace(/z$/, "Z");
  if (!instantSchema.safeParse(time).success || time.startsWith("0000-")) fail();
  const match = /^(.*T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$/.exec(time);
  if (match === null) fail();
  return (
    BigInt(Date.parse(`${match[1]}${match[3]}`)) * 1_000_000n +
    BigInt((match[2] ?? "").padEnd(9, "0"))
  );
}

/** One returned recent window only. Do not infer a rule revision or trigger-time market price. */
export function readAlertHistory(value: unknown): AlertHistoryModel {
  const workspace = record(value);
  if (
    workspace.schemaVersion !== "watchlist-alerts-workspace-v1" ||
    workspace.ruleLanguage !== "BOUNDED_COMPARISON_V1" ||
    workspace.dataMeaning !== "RESEARCH_ALERTS_ONLY_NO_ORDER_PATH" ||
    !Array.isArray(workspace.history) ||
    workspace.history.length > 200
  )
    fail();
  const cutoff = instant(workspace.generatedAt);
  const seen = new Set<string>();
  const rows = workspace.history.map((value): WatchlistAlertHistory => {
    const r = record(value);
    const id = digest(r.historyId);
    if (
      r.schemaVersion !== "watchlist-alert-history-v1" ||
      seen.has(id) ||
      typeof r.instrumentId !== "string" ||
      !isCanonicalInstrumentId(r.instrumentId)
    )
      fail();
    seen.add(id);
    const eventTime = text(r.eventTime),
      availableTime = text(r.availableTime),
      createdAt = text(r.createdAt);
    if (
      instant(eventTime) > instant(availableTime) ||
      instant(availableTime) > instant(createdAt) ||
      instant(createdAt) > cutoff
    )
      fail();
    if (
      r.observedValue !== null &&
      (typeof r.observedValue !== "string" ||
        r.observedValue.length > 128 ||
        !/^-?(?:0|[1-9]\d*)(?:\.\d{1,8})?$/.test(r.observedValue))
    )
      fail();
    const outcome = choice(r.outcome, ALERT_HISTORY_OUTCOMES);
    const delivery = choice(r.notificationStatus, ALERT_HISTORY_DELIVERY);
    const notificationId = r.notificationId === null ? null : digest(r.notificationId);
    if (
      (outcome === "TRIGGERED") !== (notificationId !== null) ||
      (notificationId === null) !== (delivery === "NONE")
    )
      fail();
    return {
      schemaVersion: "watchlist-alert-history-v1",
      historyId: id,
      ruleId: digest(r.ruleId),
      revisionId: digest(r.revisionId),
      eventId: text(r.eventId, 128),
      instrumentId: r.instrumentId,
      eventTime,
      availableTime,
      createdAt,
      outcome,
      observedValue: r.observedValue,
      notificationId,
      notificationStatus: delivery,
      detail: text(r.detail, 240),
    };
  });
  rows.sort((a, b) => {
    const left = instant(a.availableTime),
      right = instant(b.availableTime);
    return left < right
      ? 1
      : left > right
        ? -1
        : a.historyId < b.historyId
          ? 1
          : a.historyId > b.historyId
            ? -1
            : 0;
  });
  return { generatedAt: text(workspace.generatedAt), rows };
}

export function selectAlertHistory(
  rows: readonly WatchlistAlertHistory[],
  filters: AlertHistoryFilters,
  requestedPage: number,
) {
  const query = filters.query.trim().toUpperCase();
  const filtered = rows.filter(
    (row) =>
      (row.instrumentId.toUpperCase().includes(query) ||
        row.ruleId.toUpperCase().includes(query)) &&
      (filters.outcome === "ALL" || row.outcome === filters.outcome) &&
      (filters.delivery === "ALL" || row.notificationStatus === filters.delivery),
  );
  const pageCount = Math.max(1, Math.ceil(filtered.length / 20));
  const page = Math.min(
    pageCount,
    Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1,
  );
  return {
    rows: filtered.slice((page - 1) * 20, page * 20),
    count: filtered.length,
    page,
    pageCount,
  };
}

export function formatAlertHistoryTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).format(new Date(value));
}
