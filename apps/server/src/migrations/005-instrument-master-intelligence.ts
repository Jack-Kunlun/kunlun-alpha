import type { Migration } from "@kunlun/db";

export const migrations: Migration[] = [
  {
    version: 5,
    name: "instrument_master_intelligence_projection",
    up: [
      {
        name: "instrument_master_revisions",
        columns: [
          { name: "revision_id", type: "TEXT", primaryKey: true, notNull: true },
          { name: "previous_revision_id", type: "TEXT" },
          { name: "instrument_id", type: "TEXT", notNull: true },
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
          "CONSTRAINT instrument_master_code_ck CHECK (char_length(instrument_id) = 9 AND translate(substring(instrument_id, 1, 6), '0123456789', '') = '' AND substring(instrument_id, 7, 1) = '.' AND substring(instrument_id, 8, 2) IN ('SH', 'SZ', 'BJ'))",
          "CONSTRAINT instrument_master_validity_ck CHECK (effective_to IS NULL OR effective_from < effective_to)",
          "CONSTRAINT instrument_master_visibility_ck CHECK (available_time <= processing_time)",
          "CONSTRAINT instrument_master_previous_ck CHECK (previous_revision_id IS NULL OR previous_revision_id <> revision_id)",
          "CONSTRAINT instrument_master_payload_ck CHECK (jsonb_typeof(payload) = 'object')",
          "CONSTRAINT instrument_master_fingerprint_ck CHECK (char_length(payload_fingerprint) = 71 AND substring(payload_fingerprint, 1, 6) = 'sha256' AND ascii(substring(payload_fingerprint, 7, 1)) = 58 AND translate(substring(payload_fingerprint, 8, 64), '0123456789abcdef', '') = '')",
        ],
        indexes: [
          {
            name: "instrument_master_identity_visibility_idx",
            columns: [
              "instrument_id",
              "effective_from",
              "available_time",
              "processing_time",
              "revision_id",
            ],
          },
          {
            name: "instrument_master_previous_uq",
            columns: ["instrument_id", "previous_revision_id"],
            unique: true,
            predicate: "previous_revision_id IS NOT NULL",
          },
        ],
      },
    ],
    down: ["instrument_master_revisions"],
  },
];
