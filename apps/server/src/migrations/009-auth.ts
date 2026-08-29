import type { Migration } from "@kunlun/db";

export const migrations: Migration[] = [
  {
    version: 9,
    name: "local_administrator_authentication",
    up: [
      {
        name: "auth_users",
        columns: [
          { name: "user_id", type: "UUID", primaryKey: true, notNull: true },
          { name: "username", type: "TEXT", notNull: true },
          { name: "display_name", type: "TEXT", notNull: true },
          { name: "password_hash", type: "TEXT", notNull: true },
          { name: "roles", type: "JSONB", notNull: true },
          { name: "disabled", type: "BOOLEAN", notNull: true },
          { name: "created_at", type: "TIMESTAMPTZ", notNull: true },
          { name: "updated_at", type: "TIMESTAMPTZ", notNull: true },
        ],
        constraints: [
          "CONSTRAINT auth_user_username_ck CHECK (char_length(username) BETWEEN 3 AND 64 AND username = lower(username) AND translate(username, 'abcdefghijklmnopqrstuvwxyz0123456789._-', '') = '' AND (substring(username, 1, 1) BETWEEN 'a' AND 'z' OR substring(username, 1, 1) BETWEEN '0' AND '9'))",
          "CONSTRAINT auth_user_display_name_ck CHECK (char_length(display_name) BETWEEN 1 AND 80)",
          "CONSTRAINT auth_user_password_hash_ck CHECK (char_length(password_hash) BETWEEN 120 AND 180 AND ascii(substring(password_hash, 1, 1)) = 36 AND substring(password_hash, 2, 6) = 'scrypt' AND ascii(substring(password_hash, 8, 1)) = 36 AND substring(password_hash, 9, 3) = 'v=1' AND ascii(substring(password_hash, 12, 1)) = 36)",
          "CONSTRAINT auth_user_roles_ck CHECK (jsonb_typeof(roles) = 'array' AND jsonb_array_length(roles) = 1 AND roles ->> 0 = 'platform_admin')",
          "CONSTRAINT auth_user_time_ck CHECK (created_at <= updated_at)",
        ],
        indexes: [{ name: "auth_user_username_uq", columns: ["username"], unique: true }],
      },
      {
        name: "auth_sessions",
        columns: [
          { name: "session_digest", type: "TEXT", primaryKey: true, notNull: true },
          { name: "user_id", type: "UUID", notNull: true },
          { name: "created_at", type: "TIMESTAMPTZ", notNull: true },
          { name: "last_seen_at", type: "TIMESTAMPTZ", notNull: true },
          { name: "idle_expires_at", type: "TIMESTAMPTZ", notNull: true },
          { name: "absolute_expires_at", type: "TIMESTAMPTZ", notNull: true },
          { name: "revoked_at", type: "TIMESTAMPTZ" },
        ],
        constraints: [
          "CONSTRAINT auth_session_digest_ck CHECK (char_length(session_digest) = 64 AND translate(session_digest, '0123456789abcdef', '') = '')",
          "CONSTRAINT auth_session_user_fk FOREIGN KEY (user_id) REFERENCES auth_users(user_id)",
          "CONSTRAINT auth_session_time_ck CHECK (created_at <= last_seen_at AND last_seen_at <= idle_expires_at AND idle_expires_at <= absolute_expires_at)",
          "CONSTRAINT auth_session_revoked_time_ck CHECK (revoked_at IS NULL OR created_at <= revoked_at)",
        ],
        indexes: [
          { name: "auth_session_user_idx", columns: ["user_id", "absolute_expires_at"] },
          { name: "auth_session_expiry_idx", columns: ["idle_expires_at", "absolute_expires_at"] },
        ],
      },
      {
        name: "auth_login_attempts",
        columns: [
          { name: "attempt_id", type: "UUID", primaryKey: true, notNull: true },
          { name: "username_digest", type: "TEXT", notNull: true },
          { name: "attempted_at", type: "TIMESTAMPTZ", notNull: true },
          { name: "outcome", type: "TEXT", notNull: true },
        ],
        constraints: [
          "CONSTRAINT auth_attempt_username_digest_ck CHECK (char_length(username_digest) = 64 AND translate(username_digest, '0123456789abcdef', '') = '')",
          "CONSTRAINT auth_attempt_outcome_ck CHECK (outcome IN ('SUCCESS', 'FAILURE', 'THROTTLED'))",
        ],
        indexes: [
          {
            name: "auth_attempt_username_time_idx",
            columns: ["username_digest", "attempted_at"],
          },
          { name: "auth_attempt_time_outcome_idx", columns: ["attempted_at", "outcome"] },
        ],
      },
    ],
    down: ["auth_login_attempts", "auth_sessions", "auth_users"],
  },
];
