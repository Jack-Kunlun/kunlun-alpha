import type { Migration } from "@kunlun/db";

export const migrations: Migration[] = [
  {
    version: 3,
    name: "event_intelligence_read_models",
    up: [
      {
        name: "market_events",
        columns: [
          { name: "event_id", type: "TEXT", primaryKey: true, notNull: true },
          { name: "event_type", type: "TEXT", notNull: true },
          { name: "available_time", type: "TIMESTAMPTZ", notNull: true },
          { name: "confidence_bps", type: "INTEGER", notNull: true },
          { name: "instrument_ids", type: "JSONB", notNull: true },
          { name: "model_configuration_fingerprint", type: "TEXT", notNull: true },
          { name: "payload", type: "JSONB", notNull: true },
          { name: "created_at", type: "TIMESTAMPTZ", notNull: true },
        ],
      },
      {
        name: "hot_topic_snapshots",
        columns: [
          { name: "snapshot_id", type: "TEXT", primaryKey: true, notNull: true },
          { name: "topic_id", type: "TEXT", notNull: true },
          { name: "decision_time", type: "TIMESTAMPTZ", notNull: true },
          { name: "lifecycle", type: "TEXT", notNull: true },
          { name: "score_bps", type: "INTEGER", notNull: true },
          { name: "algorithm_version", type: "TEXT", notNull: true },
          { name: "policy_fingerprint", type: "TEXT", notNull: true },
          { name: "payload", type: "JSONB", notNull: true },
          { name: "created_at", type: "TIMESTAMPTZ", notNull: true },
        ],
      },
    ],
    down: ["hot_topic_snapshots", "market_events"],
  },
];
