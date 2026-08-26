import type { Migration } from "@kunlun/db";

export const migrations: Migration[] = [
  {
    version: 7,
    name: "seat_kol_intelligence_projection",
    up: [
      {
        name: "seat_trade_intelligence_revisions",
        columns: [
          { name: "revision_id", type: "TEXT", primaryKey: true, notNull: true },
          { name: "previous_revision_id", type: "TEXT" },
          { name: "trade_id", type: "TEXT", notNull: true },
          { name: "instrument_id", type: "TEXT", notNull: true },
          { name: "seat_id", type: "TEXT", notNull: true },
          { name: "event_time", type: "TIMESTAMPTZ", notNull: true },
          { name: "available_time", type: "TIMESTAMPTZ", notNull: true },
          { name: "processing_time", type: "TIMESTAMPTZ", notNull: true },
          { name: "evidence_id", type: "TEXT", notNull: true },
          { name: "payload_fingerprint", type: "TEXT", notNull: true },
          { name: "payload", type: "JSONB", notNull: true },
          { name: "created_at", type: "TIMESTAMPTZ", notNull: true },
        ],
        constraints: [
          "CONSTRAINT seat_trade_code_ck CHECK (instrument_id ~ '^[0-9]{6}\\.(SH|SZ|BJ)$')",
          "CONSTRAINT seat_trade_visibility_ck CHECK (event_time <= available_time AND available_time <= processing_time)",
          "CONSTRAINT seat_trade_previous_ck CHECK (previous_revision_id IS NULL OR previous_revision_id <> revision_id)",
          "CONSTRAINT seat_trade_payload_ck CHECK (jsonb_typeof(payload) = 'object')",
          "CONSTRAINT seat_trade_fingerprint_ck CHECK (payload_fingerprint ~ '^sha256:[0-9a-f]{64}$')",
        ],
        indexes: [
          {
            name: "seat_trade_instrument_visibility_idx",
            columns: [
              "instrument_id",
              "event_time",
              "available_time",
              "processing_time",
              "trade_id",
            ],
          },
        ],
      },
      {
        name: "kol_claim_intelligence_revisions",
        columns: [
          { name: "revision_id", type: "TEXT", primaryKey: true, notNull: true },
          { name: "previous_revision_id", type: "TEXT" },
          { name: "claim_id", type: "TEXT", notNull: true },
          { name: "instrument_id", type: "TEXT", notNull: true },
          { name: "kol_id", type: "TEXT", notNull: true },
          { name: "event_time", type: "TIMESTAMPTZ", notNull: true },
          { name: "available_time", type: "TIMESTAMPTZ", notNull: true },
          { name: "processing_time", type: "TIMESTAMPTZ", notNull: true },
          { name: "deleted", type: "BOOLEAN", notNull: true },
          { name: "payload_fingerprint", type: "TEXT", notNull: true },
          { name: "payload", type: "JSONB", notNull: true },
          { name: "created_at", type: "TIMESTAMPTZ", notNull: true },
        ],
        constraints: [
          "CONSTRAINT kol_claim_code_ck CHECK (instrument_id ~ '^[0-9]{6}\\.(SH|SZ|BJ)$')",
          "CONSTRAINT kol_claim_visibility_ck CHECK (processing_time <= available_time)",
          "CONSTRAINT kol_claim_previous_ck CHECK (previous_revision_id IS NULL OR previous_revision_id <> revision_id)",
          "CONSTRAINT kol_claim_payload_ck CHECK (jsonb_typeof(payload) = 'object')",
          "CONSTRAINT kol_claim_fingerprint_ck CHECK (payload_fingerprint ~ '^sha256:[0-9a-f]{64}$')",
        ],
        indexes: [
          {
            name: "kol_claim_instrument_visibility_idx",
            columns: [
              "instrument_id",
              "available_time",
              "processing_time",
              "claim_id",
              "revision_id",
            ],
          },
        ],
      },
      {
        name: "intelligence_evidence_revisions",
        columns: [
          { name: "revision_id", type: "TEXT", primaryKey: true, notNull: true },
          { name: "previous_revision_id", type: "TEXT" },
          { name: "evidence_id", type: "TEXT", notNull: true },
          { name: "available_time", type: "TIMESTAMPTZ", notNull: true },
          { name: "processing_time", type: "TIMESTAMPTZ", notNull: true },
          { name: "source", type: "TEXT", notNull: true },
          { name: "source_version", type: "TEXT", notNull: true },
          { name: "payload_fingerprint", type: "TEXT", notNull: true },
          { name: "payload", type: "JSONB", notNull: true },
          { name: "created_at", type: "TIMESTAMPTZ", notNull: true },
        ],
        constraints: [
          "CONSTRAINT intelligence_evidence_visibility_ck CHECK (available_time <= processing_time)",
          "CONSTRAINT intelligence_evidence_previous_ck CHECK (previous_revision_id IS NULL OR previous_revision_id <> revision_id)",
          "CONSTRAINT intelligence_evidence_payload_ck CHECK (jsonb_typeof(payload) = 'object')",
          "CONSTRAINT intelligence_evidence_fingerprint_ck CHECK (payload_fingerprint ~ '^sha256:[0-9a-f]{64}$')",
        ],
        indexes: [
          {
            name: "intelligence_evidence_visibility_idx",
            columns: ["evidence_id", "available_time", "processing_time", "revision_id"],
          },
        ],
      },
    ],
    down: [
      "intelligence_evidence_revisions",
      "kol_claim_intelligence_revisions",
      "seat_trade_intelligence_revisions",
    ],
  },
];
