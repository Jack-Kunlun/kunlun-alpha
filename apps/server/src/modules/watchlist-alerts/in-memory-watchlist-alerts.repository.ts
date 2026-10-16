import type { WatchlistAlertsRepository } from "./watchlist-alerts.repository";
import type {
  AppendHistoryResult,
  InAppNotificationList,
  NotificationEnvelope,
  StoredWatchlistAlertRule,
  WatchlistAlertHistory,
} from "./watchlist-alerts.types";

export class InMemoryWatchlistAlertsRepository implements WatchlistAlertsRepository {
  private readonly rules: StoredWatchlistAlertRule[] = [];
  private readonly history = new Map<string, { ownerRef: string; item: WatchlistAlertHistory }>();
  private readonly notifications = new Map<
    string,
    {
      ownerRef: string;
      envelope: NotificationEnvelope;
      status: "PENDING" | "DELIVERED" | "FAILED";
      attempts: number;
    }
  >();
  private readonly notificationReadReceipts = new Map<string, string>();

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

  async appendRule(
    revision: StoredWatchlistAlertRule,
    expectedRevision: number,
  ): Promise<"APPENDED" | "DUPLICATE" | "STALE" | "COMMAND_CONFLICT"> {
    const command = this.rules.find(
      (item) =>
        item.ownerRef === revision.ownerRef && item.commandRequestId === revision.commandRequestId,
    );
    if (command) {
      return command.commandHash === revision.commandHash ? "DUPLICATE" : "COMMAND_CONFLICT";
    }

    const latest = this.rules.reduce<StoredWatchlistAlertRule | null>((current, item) => {
      if (item.ownerRef !== revision.ownerRef || item.rule.ruleId !== revision.rule.ruleId) {
        return current;
      }
      return !current || current.rule.revision < item.rule.revision ? item : current;
    }, null);
    const actualRevision = latest?.rule.revision ?? 0;
    if (
      actualRevision !== expectedRevision ||
      revision.rule.revision !== expectedRevision + 1 ||
      revision.rule.previousRevisionId !== (latest?.rule.revisionId ?? null)
    ) {
      return "STALE";
    }

    this.rules.push(structuredClone(revision));
    return "APPENDED";
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
        attempts: 0,
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
    if (notification?.ownerRef === ownerRef && notification.status === "PENDING") {
      notification.status = status;
      notification.attempts += 1;
    }
  }

  async listNotifications(ownerRef: string, limit: number): Promise<InAppNotificationList> {
    const all = [...this.notifications.values()]
      .filter((item) => item.ownerRef === ownerRef)
      .flatMap((item) => {
        const history = this.history.get(item.envelope.historyId)?.item;
        if (!history) return [];
        return [
          {
            envelope: structuredClone(item.envelope),
            ruleId: history.ruleId,
            instrumentId: history.instrumentId,
            deliveryStatus: item.status,
            deliveryAttempts: item.attempts,
            readAt: this.notificationReadReceipts.get(item.envelope.notificationId) ?? null,
          },
        ];
      })
      .sort(
        (left, right) =>
          right.envelope.availableAt.localeCompare(left.envelope.availableAt) ||
          right.envelope.notificationId.localeCompare(left.envelope.notificationId),
      );
    return {
      notifications: all.slice(0, limit),
      unreadCount: all.filter((item) => item.readAt === null).length,
    };
  }

  async markNotificationRead(
    ownerRef: string,
    notificationId: string,
    readAt: string,
  ): Promise<boolean> {
    const notification = this.notifications.get(notificationId);
    if (notification?.ownerRef !== ownerRef) return false;
    if (!this.notificationReadReceipts.has(notificationId)) {
      this.notificationReadReceipts.set(notificationId, readAt);
    }
    return true;
  }

  async markAllNotificationsRead(ownerRef: string, readAt: string): Promise<number> {
    let inserted = 0;
    for (const [notificationId, notification] of this.notifications) {
      if (
        notification.ownerRef === ownerRef &&
        !this.notificationReadReceipts.has(notificationId)
      ) {
        this.notificationReadReceipts.set(notificationId, readAt);
        inserted += 1;
      }
    }
    return inserted;
  }
}
