import type { Migration } from "@kunlun/db";

export const migrations: Migration[] = [
  {
    version: 10,
    name: "watchlist_notification_read_receipts",
    up: [
      {
        name: "watchlist_notification_receipts",
        columns: [
          { name: "notification_id", type: "TEXT", primaryKey: true, notNull: true },
          { name: "owner_ref", type: "TEXT", notNull: true },
          { name: "read_at", type: "TIMESTAMPTZ", notNull: true },
        ],
        constraints: [
          "CONSTRAINT watchlist_notification_receipt_fk FOREIGN KEY (notification_id) REFERENCES watchlist_notification_outbox(notification_id)",
          "CONSTRAINT watchlist_notification_receipt_owner_ck CHECK (char_length(owner_ref) BETWEEN 1 AND 128)",
        ],
        indexes: [
          {
            name: "watchlist_notification_receipt_owner_time_idx",
            columns: ["owner_ref", "read_at", "notification_id"],
          },
        ],
      },
    ],
    down: ["watchlist_notification_receipts"],
  },
];
