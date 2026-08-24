import type { Migration } from "@kunlun/db";

export const migrations: Migration[] = [
  {
    version: 2,
    name: "append_only_event_feedback",
    up: [
      {
        name: "event_feedback",
        columns: [
          { name: "feedback_id", type: "TEXT", primaryKey: true, notNull: true },
          { name: "client_request_id", type: "TEXT", notNull: true },
          { name: "event_id", type: "TEXT", notNull: true },
          { name: "model_configuration_fingerprint", type: "TEXT", notNull: true },
          { name: "action", type: "TEXT", notNull: true },
          { name: "reason_code", type: "TEXT", notNull: true },
          { name: "correction", type: "JSONB" },
          { name: "comment", type: "TEXT" },
          { name: "reviewer_ref", type: "TEXT", notNull: true },
          { name: "submission_fingerprint", type: "TEXT", notNull: true },
          { name: "created_at", type: "TIMESTAMPTZ", notNull: true },
          { name: "available_at", type: "TIMESTAMPTZ", notNull: true },
        ],
      },
    ],
    down: ["event_feedback"],
  },
];
