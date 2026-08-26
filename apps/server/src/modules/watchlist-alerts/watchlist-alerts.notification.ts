import type { NotificationEnvelope } from "./watchlist-alerts.types";

export interface WatchlistAlertNotificationDispatcher {
  deliver(notification: NotificationEnvelope): Promise<void>;
}

export class InAppWatchlistAlertNotificationDispatcher implements WatchlistAlertNotificationDispatcher {
  async deliver(_notification: NotificationEnvelope): Promise<void> {
    // The durable outbox row is the in-app notification. External channels are
    // intentionally not part of this bounded research-terminal capability.
    await Promise.resolve();
  }
}
