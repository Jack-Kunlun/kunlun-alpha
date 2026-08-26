import type { Migration } from "@kunlun/db";

export const migrations: Migration[] = [
  {
    version: 8,
    name: "watchlist_alert_rules_and_delivery_history",
    up: [
      {
        name: "watchlist_alert_rule_revisions",
        columns: [
          { name: "revision_id", type: "TEXT", primaryKey: true, notNull: true },
          { name: "rule_id", type: "TEXT", notNull: true },
          { name: "owner_ref", type: "TEXT", notNull: true },
          { name: "command_request_id", type: "TEXT", notNull: true },
          { name: "command_hash", type: "TEXT", notNull: true },
          { name: "revision", type: "INTEGER", notNull: true },
          { name: "enabled", type: "BOOLEAN", notNull: true },
          { name: "available_at", type: "TIMESTAMPTZ", notNull: true },
          { name: "payload", type: "JSONB", notNull: true },
          { name: "created_at", type: "TIMESTAMPTZ", notNull: true },
        ],
        constraints: [
          "CONSTRAINT watchlist_rule_revision_ck CHECK (revision >= 1)",
          "CONSTRAINT watchlist_rule_time_ck CHECK (created_at <= available_at)",
          "CONSTRAINT watchlist_rule_payload_ck CHECK (jsonb_typeof(payload) = 'object')",
          "CONSTRAINT watchlist_rule_id_ck CHECK (char_length(rule_id) = 64 AND translate(rule_id, '0123456789abcdef', '') = '')",
          "CONSTRAINT watchlist_revision_id_ck CHECK (char_length(revision_id) = 64 AND translate(revision_id, '0123456789abcdef', '') = '')",
          "CONSTRAINT watchlist_command_hash_ck CHECK (char_length(command_hash) = 64 AND translate(command_hash, '0123456789abcdef', '') = '')",
        ],
        indexes: [
          {
            name: "watchlist_rule_revision_uq",
            columns: ["rule_id", "revision"],
            unique: true,
          },
          {
            name: "watchlist_rule_command_uq",
            columns: ["owner_ref", "command_request_id"],
            unique: true,
          },
          {
            name: "watchlist_rule_owner_latest_idx",
            columns: ["owner_ref", "rule_id", "revision"],
          },
        ],
      },
      {
        name: "watchlist_alert_history",
        columns: [
          { name: "history_id", type: "TEXT", primaryKey: true, notNull: true },
          { name: "owner_ref", type: "TEXT", notNull: true },
          { name: "rule_id", type: "TEXT", notNull: true },
          { name: "revision_id", type: "TEXT", notNull: true },
          { name: "event_id", type: "TEXT", notNull: true },
          { name: "instrument_id", type: "TEXT", notNull: true },
          { name: "available_time", type: "TIMESTAMPTZ", notNull: true },
          { name: "outcome", type: "TEXT", notNull: true },
          { name: "notification_id", type: "TEXT" },
          { name: "payload", type: "JSONB", notNull: true },
          { name: "created_at", type: "TIMESTAMPTZ", notNull: true },
        ],
        constraints: [
          "CONSTRAINT watchlist_history_time_ck CHECK (available_time <= created_at)",
          "CONSTRAINT watchlist_history_outcome_ck CHECK (outcome IN ('TRIGGERED', 'CONDITION_NOT_MET', 'THROTTLED', 'QUIET_PERIOD', 'RULE_DISABLED'))",
          "CONSTRAINT watchlist_history_payload_ck CHECK (jsonb_typeof(payload) = 'object')",
          "CONSTRAINT watchlist_history_instrument_ck CHECK (char_length(instrument_id) = 9 AND translate(substring(instrument_id, 1, 6), '0123456789', '') = '' AND substring(instrument_id, 7, 1) = '.' AND substring(instrument_id, 8, 2) IN ('SH', 'SZ', 'BJ'))",
        ],
        indexes: [
          {
            name: "watchlist_history_event_uq",
            columns: ["rule_id", "revision_id", "event_id"],
            unique: true,
          },
          {
            name: "watchlist_history_owner_time_idx",
            columns: ["owner_ref", "available_time", "history_id"],
          },
        ],
      },
      {
        name: "watchlist_notification_outbox",
        columns: [
          { name: "notification_id", type: "TEXT", primaryKey: true, notNull: true },
          { name: "history_id", type: "TEXT", notNull: true },
          { name: "owner_ref", type: "TEXT", notNull: true },
          { name: "status", type: "TEXT", notNull: true },
          { name: "attempts", type: "INTEGER", notNull: true },
          { name: "last_error", type: "TEXT" },
          { name: "payload", type: "JSONB", notNull: true },
          { name: "available_at", type: "TIMESTAMPTZ", notNull: true },
          { name: "updated_at", type: "TIMESTAMPTZ", notNull: true },
        ],
        constraints: [
          "CONSTRAINT watchlist_outbox_status_ck CHECK (status IN ('PENDING', 'DELIVERED', 'FAILED'))",
          "CONSTRAINT watchlist_outbox_attempts_ck CHECK (attempts >= 0)",
          "CONSTRAINT watchlist_outbox_time_ck CHECK (available_at <= updated_at)",
          "CONSTRAINT watchlist_outbox_payload_ck CHECK (jsonb_typeof(payload) = 'object')",
        ],
        indexes: [
          {
            name: "watchlist_outbox_history_uq",
            columns: ["history_id"],
            unique: true,
          },
          {
            name: "watchlist_outbox_delivery_idx",
            columns: ["status", "available_at", "notification_id"],
          },
        ],
      },
    ],
    down: [
      "watchlist_notification_outbox",
      "watchlist_alert_history",
      "watchlist_alert_rule_revisions",
    ],
  },
];
