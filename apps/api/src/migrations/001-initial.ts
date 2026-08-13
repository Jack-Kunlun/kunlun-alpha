import type { Migration } from "@kunlun/db";

/**
 * Initial business model: control-plane tables for providers, tasks,
 * checkpoints, data versions and quality events. High-frequency market data
 * deliberately lives in ClickHouse (P1-N10), never here.
 */
export const migrations: Migration[] = [
  {
    version: 1,
    name: "initial_business_model",
    up: [
      {
        name: "providers",
        columns: [
          { name: "id", type: "TEXT", primaryKey: true, notNull: true },
          { name: "name", type: "TEXT", notNull: true },
          { name: "capabilities", type: "TEXT", notNull: true },
        ],
      },
      {
        name: "tasks",
        columns: [
          { name: "id", type: "TEXT", primaryKey: true, notNull: true },
          { name: "kind", type: "TEXT", notNull: true },
          { name: "status", type: "TEXT", notNull: true },
          { name: "lease_until", type: "TIMESTAMPTZ" },
          { name: "created_at", type: "TIMESTAMPTZ", notNull: true },
        ],
      },
      {
        name: "checkpoints",
        columns: [
          { name: "task_id", type: "TEXT", primaryKey: true, notNull: true },
          { name: "cursor", type: "TEXT" },
          { name: "updated_at", type: "TIMESTAMPTZ", notNull: true },
        ],
      },
      {
        name: "data_versions",
        columns: [
          { name: "id", type: "TEXT", primaryKey: true, notNull: true },
          { name: "source", type: "TEXT", notNull: true },
          { name: "date", type: "DATE", notNull: true },
          { name: "checksum", type: "TEXT", notNull: true },
        ],
      },
      {
        name: "quality_events",
        columns: [
          { name: "id", type: "TEXT", primaryKey: true, notNull: true },
          { name: "kind", type: "TEXT", notNull: true },
          { name: "unified_code", type: "TEXT" },
          { name: "date", type: "DATE" },
          { name: "detail", type: "TEXT" },
        ],
      },
    ],
    down: ["quality_events", "data_versions", "checkpoints", "tasks", "providers"],
  },
];
