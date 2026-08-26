import { Pool } from "pg";
import type { WatchlistAlertsRepository } from "./watchlist-alerts.repository";
import type {
  AppendHistoryResult,
  NotificationEnvelope,
  StoredWatchlistAlertRule,
  WatchlistAlertHistory,
} from "./watchlist-alerts.types";

export class PostgresWatchlistAlertsRepository implements WatchlistAlertsRepository {
  private readonly pool: Pool;

  constructor(connectionString: string) {
    this.pool = new Pool({ connectionString });
  }

  async listLatestRules(ownerRef: string): Promise<StoredWatchlistAlertRule[]> {
    const result = await this.pool.query<{ payload: StoredWatchlistAlertRule }>(
      `SELECT DISTINCT ON (rule_id) payload
       FROM watchlist_alert_rule_revisions
       WHERE owner_ref = $1
       ORDER BY rule_id, revision DESC`,
      [ownerRef],
    );
    return result.rows
      .map((row) => row.payload)
      .sort((left, right) => left.rule.name.localeCompare(right.rule.name));
  }

  async findLatestRule(ownerRef: string, ruleId: string): Promise<StoredWatchlistAlertRule | null> {
    const result = await this.pool.query<{ payload: StoredWatchlistAlertRule }>(
      `SELECT payload
       FROM watchlist_alert_rule_revisions
       WHERE owner_ref = $1 AND rule_id = $2
       ORDER BY revision DESC
       LIMIT 1`,
      [ownerRef, ruleId],
    );
    return result.rows[0]?.payload ?? null;
  }

  async findRuleByCommand(
    ownerRef: string,
    commandRequestId: string,
  ): Promise<StoredWatchlistAlertRule | null> {
    const result = await this.pool.query<{ payload: StoredWatchlistAlertRule }>(
      `SELECT payload
       FROM watchlist_alert_rule_revisions
       WHERE owner_ref = $1 AND command_request_id = $2
       LIMIT 1`,
      [ownerRef, commandRequestId],
    );
    return result.rows[0]?.payload ?? null;
  }

  async appendRule(revision: StoredWatchlistAlertRule): Promise<void> {
    await this.pool.query(
      `INSERT INTO watchlist_alert_rule_revisions (
         revision_id, rule_id, owner_ref, command_request_id, command_hash,
         revision, enabled, available_at, payload, created_at
       ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
       ON CONFLICT (owner_ref, command_request_id) DO NOTHING`,
      [
        revision.rule.revisionId,
        revision.rule.ruleId,
        revision.ownerRef,
        revision.commandRequestId,
        revision.commandHash,
        revision.rule.revision,
        revision.rule.enabled,
        revision.rule.availableAt,
        JSON.stringify(revision),
        revision.rule.createdAt,
      ],
    );
  }

  async listHistory(ownerRef: string, limit: number): Promise<WatchlistAlertHistory[]> {
    const result = await this.pool.query<{
      payload: WatchlistAlertHistory;
      notification_status: WatchlistAlertHistory["notificationStatus"] | null;
    }>(
      `SELECT history.payload, notification.status AS notification_status
       FROM watchlist_alert_history AS history
       LEFT JOIN watchlist_notification_outbox AS notification
         ON notification.notification_id = history.notification_id
       WHERE history.owner_ref = $1
       ORDER BY history.available_time DESC, history.history_id DESC
       LIMIT $2`,
      [ownerRef, limit],
    );
    return result.rows.map((row) => ({
      ...row.payload,
      notificationStatus: row.notification_status ?? row.payload.notificationStatus,
    }));
  }

  async appendHistory(
    ownerRef: string,
    history: WatchlistAlertHistory,
    notification: NotificationEnvelope | null,
  ): Promise<AppendHistoryResult> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      const inserted = await client.query<{ payload: WatchlistAlertHistory }>(
        `INSERT INTO watchlist_alert_history (
           history_id, owner_ref, rule_id, revision_id, event_id, instrument_id,
           available_time, outcome, notification_id, payload, created_at
         ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11)
         ON CONFLICT (rule_id, revision_id, event_id) DO NOTHING
         RETURNING payload`,
        [
          history.historyId,
          ownerRef,
          history.ruleId,
          history.revisionId,
          history.eventId,
          history.instrumentId,
          history.availableTime,
          history.outcome,
          history.notificationId,
          JSON.stringify(history),
          history.createdAt,
        ],
      );
      if (inserted.rowCount === 0) {
        const existing = await client.query<{ payload: WatchlistAlertHistory }>(
          `SELECT payload
           FROM watchlist_alert_history
           WHERE rule_id = $1 AND revision_id = $2 AND event_id = $3`,
          [history.ruleId, history.revisionId, history.eventId],
        );
        await client.query("COMMIT");
        return { history: existing.rows[0]?.payload ?? history, duplicate: true };
      }
      if (notification) {
        await client.query(
          `INSERT INTO watchlist_notification_outbox (
             notification_id, history_id, owner_ref, status, attempts, last_error,
             payload, available_at, updated_at
           ) VALUES ($1, $2, $3, 'PENDING', 0, NULL, $4::jsonb, $5, $5)
           ON CONFLICT (history_id) DO NOTHING`,
          [
            notification.notificationId,
            notification.historyId,
            ownerRef,
            JSON.stringify(notification),
            notification.availableAt,
          ],
        );
      }
      await client.query("COMMIT");
      return { history, duplicate: false };
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }

  async findLatestTriggeredTime(
    ownerRef: string,
    ruleId: string,
    availableAtOrBefore: string,
  ): Promise<string | null> {
    const result = await this.pool.query<{ available_time: Date | string }>(
      `SELECT available_time
       FROM watchlist_alert_history
       WHERE owner_ref = $1 AND rule_id = $2 AND outcome = 'TRIGGERED'
         AND available_time <= $3
       ORDER BY available_time DESC
       LIMIT 1`,
      [ownerRef, ruleId, availableAtOrBefore],
    );
    const value = result.rows[0]?.available_time;
    if (!value) return null;
    return value instanceof Date ? value.toISOString() : new Date(value).toISOString();
  }

  async markNotification(
    ownerRef: string,
    notificationId: string,
    status: "DELIVERED" | "FAILED",
    error: string | null,
    updatedAt: string,
  ): Promise<void> {
    await this.pool.query(
      `UPDATE watchlist_notification_outbox
       SET status = $1, attempts = attempts + 1, last_error = $2, updated_at = $3
       WHERE owner_ref = $4 AND notification_id = $5 AND status = 'PENDING'`,
      [status, error, updatedAt, ownerRef, notificationId],
    );
  }
}
