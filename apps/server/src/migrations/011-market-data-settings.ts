import type { Migration } from "@kunlun/db";

/**
 * Singleton instance settings for the market-data worker.
 *
 * The token columns contain only AES-256-GCM envelope parts.  The master key
 * is deliberately supplied outside PostgreSQL and the audit table contains
 * no secret, digest, or ciphertext fields.
 */
export const migrations: Migration[] = [
  {
    version: 11,
    name: "market_data_instance_settings",
    up: [
      {
        name: "market_data_instance_settings",
        columns: [
          { name: "instance_id", type: "TEXT", primaryKey: true, notNull: true },
          { name: "provider", type: "TEXT", notNull: true },
          { name: "revision", type: "INTEGER", notNull: true },
          { name: "token_ciphertext", type: "TEXT" },
          { name: "token_nonce", type: "TEXT" },
          { name: "token_tag", type: "TEXT" },
          { name: "encryption_version", type: "TEXT" },
          { name: "key_version", type: "TEXT" },
          { name: "updated_at", type: "TIMESTAMPTZ" },
        ],
        constraints: [
          "CONSTRAINT market_data_settings_instance_ck CHECK (instance_id = 'default')",
          "CONSTRAINT market_data_settings_provider_ck CHECK (provider IN ('akshare', 'tushare'))",
          "CONSTRAINT market_data_settings_revision_ck CHECK (revision >= 0)",
          "CONSTRAINT market_data_settings_envelope_ck CHECK ((token_ciphertext IS NULL AND token_nonce IS NULL AND token_tag IS NULL AND encryption_version IS NULL AND key_version IS NULL) OR (token_ciphertext IS NOT NULL AND token_nonce IS NOT NULL AND token_tag IS NOT NULL AND encryption_version IS NOT NULL AND encryption_version = 'aes-256-gcm-v1' AND key_version IS NOT NULL))",
          "CONSTRAINT market_data_settings_tushare_token_ck CHECK (provider <> 'tushare' OR (token_ciphertext IS NOT NULL AND token_nonce IS NOT NULL AND token_tag IS NOT NULL AND encryption_version = 'aes-256-gcm-v1' AND key_version IS NOT NULL))",
          "CONSTRAINT market_data_settings_updated_at_ck CHECK ((revision = 0 AND updated_at IS NULL) OR (revision > 0 AND updated_at IS NOT NULL))",
        ],
        indexes: [
          {
            name: "market_data_instance_settings_revision_idx",
            columns: ["revision"],
          },
        ],
      },
      {
        name: "market_data_settings_audit",
        columns: [
          { name: "audit_id", type: "UUID", primaryKey: true, notNull: true },
          { name: "instance_id", type: "TEXT", notNull: true },
          { name: "revision", type: "INTEGER", notNull: true },
          { name: "provider", type: "TEXT", notNull: true },
          { name: "token_action", type: "TEXT", notNull: true },
          { name: "actor_id", type: "UUID", notNull: true },
          { name: "recorded_at", type: "TIMESTAMPTZ", notNull: true },
        ],
        constraints: [
          "CONSTRAINT market_data_settings_audit_instance_fk FOREIGN KEY (instance_id) REFERENCES market_data_instance_settings(instance_id)",
          "CONSTRAINT market_data_settings_audit_revision_ck CHECK (revision > 0)",
          "CONSTRAINT market_data_settings_audit_provider_ck CHECK (provider IN ('akshare', 'tushare'))",
          "CONSTRAINT market_data_settings_audit_token_action_ck CHECK (token_action IN ('KEEP', 'REPLACE', 'CLEAR'))",
        ],
        indexes: [
          {
            name: "market_data_settings_audit_time_idx",
            columns: ["instance_id", "recorded_at", "audit_id"],
          },
          {
            name: "market_data_settings_audit_revision_uq",
            columns: ["instance_id", "revision"],
            unique: true,
          },
        ],
      },
    ],
    down: ["market_data_settings_audit", "market_data_instance_settings"],
  },
];
