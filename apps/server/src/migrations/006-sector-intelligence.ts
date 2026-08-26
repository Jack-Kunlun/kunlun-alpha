import type { Migration } from "@kunlun/db";

export const migrations: Migration[] = [
  {
    version: 6,
    name: "sector_intelligence_projection",
    up: [
      {
        name: "sector_master_revisions",
        columns: [
          { name: "revision_id", type: "TEXT", primaryKey: true, notNull: true },
          { name: "previous_revision_id", type: "TEXT" },
          { name: "sector_id", type: "TEXT", notNull: true },
          { name: "effective_from", type: "TIMESTAMPTZ", notNull: true },
          { name: "effective_to", type: "TIMESTAMPTZ" },
          { name: "available_time", type: "TIMESTAMPTZ", notNull: true },
          { name: "processing_time", type: "TIMESTAMPTZ", notNull: true },
          { name: "source", type: "TEXT", notNull: true },
          { name: "source_version", type: "TEXT", notNull: true },
          { name: "evidence_id", type: "TEXT", notNull: true },
          { name: "payload_fingerprint", type: "TEXT", notNull: true },
          { name: "payload", type: "JSONB", notNull: true },
          { name: "created_at", type: "TIMESTAMPTZ", notNull: true },
        ],
        constraints: [
          "CONSTRAINT sector_master_validity_ck CHECK (effective_to IS NULL OR effective_from < effective_to)",
          "CONSTRAINT sector_master_visibility_ck CHECK (available_time <= processing_time)",
          "CONSTRAINT sector_master_previous_ck CHECK (previous_revision_id IS NULL OR previous_revision_id <> revision_id)",
          "CONSTRAINT sector_master_payload_ck CHECK (jsonb_typeof(payload) = 'object')",
          "CONSTRAINT sector_master_fingerprint_ck CHECK (payload_fingerprint ~ '^sha256:[0-9a-f]{64}$')",
        ],
        indexes: [
          {
            name: "sector_master_visibility_idx",
            columns: [
              "sector_id",
              "effective_from",
              "available_time",
              "processing_time",
              "revision_id",
            ],
          },
        ],
      },
      {
        name: "sector_membership_revisions",
        columns: [
          { name: "revision_id", type: "TEXT", primaryKey: true, notNull: true },
          { name: "previous_revision_id", type: "TEXT" },
          { name: "instrument_id", type: "TEXT", notNull: true },
          { name: "sector_id", type: "TEXT", notNull: true },
          { name: "effective_from", type: "TIMESTAMPTZ", notNull: true },
          { name: "effective_to", type: "TIMESTAMPTZ" },
          { name: "available_time", type: "TIMESTAMPTZ", notNull: true },
          { name: "processing_time", type: "TIMESTAMPTZ", notNull: true },
          { name: "source", type: "TEXT", notNull: true },
          { name: "source_version", type: "TEXT", notNull: true },
          { name: "evidence_id", type: "TEXT", notNull: true },
          { name: "payload_fingerprint", type: "TEXT", notNull: true },
          { name: "payload", type: "JSONB", notNull: true },
          { name: "created_at", type: "TIMESTAMPTZ", notNull: true },
        ],
        constraints: [
          "CONSTRAINT sector_membership_code_ck CHECK (instrument_id ~ '^[0-9]{6}\\.(SH|SZ|BJ)$')",
          "CONSTRAINT sector_membership_validity_ck CHECK (effective_to IS NULL OR effective_from < effective_to)",
          "CONSTRAINT sector_membership_visibility_ck CHECK (available_time <= processing_time)",
          "CONSTRAINT sector_membership_previous_ck CHECK (previous_revision_id IS NULL OR previous_revision_id <> revision_id)",
          "CONSTRAINT sector_membership_payload_ck CHECK (jsonb_typeof(payload) = 'object')",
          "CONSTRAINT sector_membership_fingerprint_ck CHECK (payload_fingerprint ~ '^sha256:[0-9a-f]{64}$')",
        ],
        indexes: [
          {
            name: "sector_membership_instrument_visibility_idx",
            columns: [
              "instrument_id",
              "sector_id",
              "effective_from",
              "available_time",
              "processing_time",
              "revision_id",
            ],
          },
        ],
      },
    ],
    down: ["sector_membership_revisions", "sector_master_revisions"],
  },
];
