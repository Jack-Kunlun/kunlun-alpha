import type { Migration } from "@kunlun/db";

export const migrations: Migration[] = [
  {
    version: 12,
    name: "personal_watchlist",
    up: [
      {
        name: "personal_watchlist_items",
        columns: [
          { name: "position", type: "BIGINT", notNull: true },
          { name: "owner_id", type: "UUID", notNull: true },
          { name: "code", type: "TEXT", notNull: true },
          { name: "name", type: "TEXT", notNull: true },
          { name: "added_at", type: "TIMESTAMPTZ", notNull: true },
        ],
        constraints: [
          "FOREIGN KEY (owner_id) REFERENCES auth_users(user_id)",
          "CHECK (code ~ '^([0-9]{6}[.](SH|SZ|BJ)|HK:[0-9]{5}|NEEQ:[0-9]{6}|SGE:AU99[.]99)$')",
          "CHECK (char_length(name) BETWEEN 1 AND 80 AND name !~ '[<>[:cntrl:]]')",
        ],
        indexes: [
          { name: "personal_watchlist_owner_code_uq", columns: ["owner_id", "code"], unique: true },
        ],
      },
      {
        name: "personal_watchlist_imports",
        columns: [
          { name: "owner_id", type: "UUID", notNull: true },
          { name: "client_request_id", type: "UUID", notNull: true },
          { name: "command_hash", type: "TEXT", notNull: true },
          { name: "completed_at", type: "TIMESTAMPTZ", notNull: true },
        ],
        constraints: ["FOREIGN KEY (owner_id) REFERENCES auth_users(user_id)"],
        indexes: [
          {
            name: "personal_watchlist_command_uq",
            columns: ["owner_id", "client_request_id"],
            unique: true,
          },
        ],
      },
      {
        name: "personal_watchlist_market_state",
        columns: [
          { name: "code", type: "TEXT", primaryKey: true, notNull: true },
          { name: "status", type: "TEXT", notNull: true },
          { name: "last_attempt_at", type: "TIMESTAMPTZ" },
          { name: "last_success_at", type: "TIMESTAMPTZ" },
          { name: "error_code", type: "TEXT" },
          { name: "attempt_date", type: "DATE" },
          { name: "attempt_count", type: "INTEGER", notNull: true },
        ],
        constraints: [
          "CHECK (status IN ('RUNNING','SUCCEEDED','EMPTY','FAILED','UNSUPPORTED'))",
          "CHECK (error_code IS NULL OR error_code IN ('SOURCE_ERROR','VALIDATION_ERROR','SYNC_ERROR','UNSUPPORTED_MARKET'))",
        ],
      },
    ],
    down: [
      "personal_watchlist_market_state",
      "personal_watchlist_imports",
      "personal_watchlist_items",
    ],
  },
];
