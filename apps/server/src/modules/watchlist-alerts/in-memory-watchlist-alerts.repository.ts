import type { WatchlistAlertsRepository } from "./watchlist-alerts.repository";
import type {
  AppendHistoryResult,
  NotificationEnvelope,
  StoredWatchlistAlertRule,
  WatchlistAlertHistory,
} from "./watchlist-alerts.types";

export class InMemoryWatchlistAlertsRepository implements WatchlistAlertsRepository {
  private readonly rules: StoredWatchlistAlertRule[] = [];
  private readonly history = new Map<string, { ownerRef: string; item: WatchlistAlertHistory }>();
  private readonly notifications = new Map<
    string,
    { ownerRef: string; envelope: NotificationEnvelope; status: "PENDING" | "DELIVERED" | "FAILED" }
  >();

  async listLatestRules(ownerRef: string): Promise<StoredWatchlistAlertRule[]> {
    const latest = new Map<string, StoredWatchlistAlertRule>();
    for (const item of this.rules.filter((candidate) => candidate.ownerRef === ownerRef)) {
      const current = latest.get(item.rule.ruleId);
      if (!current || current.rule.revision < item.rule.revision)
        latest.set(item.rule.ruleId, item);
    }
    return [...latest.values()].sort((left, right) =>
      left.rule.name.localeCompare(right.rule.name),
    );
  }

  async findLatestRule(ownerRef: string, ruleId: string): Promise<StoredWatchlistAlertRule | null> {
    return (
      this.rules
        .filter((item) => item.ownerRef === ownerRef && item.rule.ruleId === ruleId)
        .sort((left, right) => right.rule.revision - left.rule.revision)[0] ?? null
    );
  }

  async findRuleByCommand(
    ownerRef: string,
    commandRequestId: string,
  ): Promise<StoredWatchlistAlertRule | null> {
    return (
      this.rules.find(
        (item) => item.ownerRef === ownerRef && item.commandRequestId === commandRequestId,
      ) ?? null
    );
  }

  async appendRule(revision: StoredWatchlistAlertRule): Promise<void> {
    const command = await this.findRuleByCommand(revision.ownerRef, revision.commandRequestId);
    if (command) return;
    this.rules.push(structuredClone(revision));
  }

  async listHistory(ownerRef: string, limit: number): Promise<WatchlistAlertHistory[]> {
    return [...this.history.values()]
      .filter((entry) => entry.ownerRef === ownerRef)
      .map(({ item }) => {
        const notification = item.notificationId
          ? this.notifications.get(item.notificationId)
          : undefined;
        return {
          ...structuredClone(item),
          notificationStatus: notification?.status ?? item.notificationStatus,
        };
      })
      .sort((left, right) => right.availableTime.localeCompare(left.availableTime))
      .slice(0, limit);
  }

  async appendHistory(
    ownerRef: string,
    history: WatchlistAlertHistory,
    notification: NotificationEnvelope | null,
  ): Promise<AppendHistoryResult> {
    const existing = this.history.get(history.historyId);
    if (existing) return { history: structuredClone(existing.item), duplicate: true };
    this.history.set(history.historyId, { ownerRef, item: structuredClone(history) });
    if (notification) {
      this.notifications.set(notification.notificationId, {
        ownerRef,
        envelope: structuredClone(notification),
        status: "PENDING",
      });
    }
    return { history: structuredClone(history), duplicate: false };
  }

  async findLatestTriggeredTime(
    ownerRef: string,
    ruleId: string,
    availableAtOrBefore: string,
  ): Promise<string | null> {
    return (
      [...this.history.values()]
        .filter(
          ({ ownerRef: itemOwner, item }) =>
            itemOwner === ownerRef &&
            item.ruleId === ruleId &&
            item.outcome === "TRIGGERED" &&
            item.availableTime <= availableAtOrBefore,
        )
        .map(({ item }) => item.availableTime)
        .sort((left, right) => right.localeCompare(left))[0] ?? null
    );
  }

  async markNotification(
    ownerRef: string,
    notificationId: string,
    status: "DELIVERED" | "FAILED",
    _error: string | null,
    _updatedAt: string,
  ): Promise<void> {
    const notification = this.notifications.get(notificationId);
    if (notification?.ownerRef === ownerRef) notification.status = status;
  }
}
