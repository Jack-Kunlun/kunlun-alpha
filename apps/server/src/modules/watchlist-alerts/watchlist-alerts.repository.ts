import type {
  AppendHistoryResult,
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
  appendRule(revision: StoredWatchlistAlertRule): Promise<void>;
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
}
