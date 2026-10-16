import type {
  AppendHistoryResult,
  InAppNotificationList,
  NotificationEnvelope,
  StoredWatchlistAlertRule,
  WatchlistAlertHistory,
} from "./watchlist-alerts.types";

export interface WatchlistAlertsRepository {
  listLatestRules(ownerRef: string): Promise<StoredWatchlistAlertRule[]>;
  findLatestRule(ownerRef: string, ruleId: string): Promise<StoredWatchlistAlertRule | null>;
  findRuleByCommand(
    ownerRef: string,
    commandRequestId: string,
  ): Promise<StoredWatchlistAlertRule | null>;
  appendRule(
    revision: StoredWatchlistAlertRule,
    expectedRevision: number,
  ): Promise<AppendWatchlistAlertRuleResult>;
  listHistory(ownerRef: string, limit: number): Promise<WatchlistAlertHistory[]>;
  appendHistory(
    ownerRef: string,
    history: WatchlistAlertHistory,
    notification: NotificationEnvelope | null,
  ): Promise<AppendHistoryResult>;
  findLatestTriggeredTime(
    ownerRef: string,
    ruleId: string,
    availableAtOrBefore: string,
  ): Promise<string | null>;
  markNotification(
    ownerRef: string,
    notificationId: string,
    status: "DELIVERED" | "FAILED",
    error: string | null,
    updatedAt: string,
  ): Promise<void>;
  listNotifications(ownerRef: string, limit: number): Promise<InAppNotificationList>;
  markNotificationRead(ownerRef: string, notificationId: string, readAt: string): Promise<boolean>;
  markAllNotificationsRead(ownerRef: string, readAt: string): Promise<number>;
}

export type AppendWatchlistAlertRuleResult =
  "APPENDED" | "DUPLICATE" | "STALE" | "COMMAND_CONFLICT";
