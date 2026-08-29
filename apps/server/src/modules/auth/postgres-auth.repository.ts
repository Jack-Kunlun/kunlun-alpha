import { randomUUID } from "node:crypto";
import type { OnModuleDestroy } from "@nestjs/common";
import type { Pool } from "pg";
import type {
  AuthRepository,
  AuthSessionRecord,
  AuthSessionSummaryRecord,
  AuthUserIdentityRecord,
  AuthUserRecord,
  LoginAttemptCounts,
  LoginAttemptOutcome,
  NewAuthSession,
  PasswordChangeCommit,
} from "./auth.types";

interface AuthUserIdentityRow {
  user_id: string;
  username: string;
  display_name: string;
  roles: unknown;
  disabled: boolean;
}

interface AuthUserRow extends AuthUserIdentityRow {
  password_hash: string;
}

interface AuthSessionRow extends AuthUserIdentityRow {
  session_digest: string;
  created_at: Date | string;
  last_seen_at: Date | string;
  idle_expires_at: Date | string;
  absolute_expires_at: Date | string;
  revoked_at: Date | string | null;
}

interface AuthSessionSummaryRow {
  session_digest: string;
  created_at: Date | string;
  last_seen_at: Date | string;
  idle_expires_at: Date | string;
  absolute_expires_at: Date | string;
}

function roles(value: unknown): ["platform_admin"] {
  if (!Array.isArray(value) || value.length !== 1 || value[0] !== "platform_admin") {
    throw new Error("authentication user roles are invalid");
  }
  return ["platform_admin"];
}

function identity(row: AuthUserIdentityRow): AuthUserIdentityRecord {
  if (
    typeof row.user_id !== "string" ||
    typeof row.username !== "string" ||
    typeof row.display_name !== "string" ||
    typeof row.disabled !== "boolean"
  ) {
    throw new Error("authentication user record is invalid");
  }
  return {
    userId: row.user_id,
    username: row.username,
    displayName: row.display_name,
    roles: roles(row.roles),
    disabled: row.disabled,
  };
}

function user(row: AuthUserRow): AuthUserRecord {
  if (typeof row.password_hash !== "string") {
    throw new Error("authentication user password record is invalid");
  }
  return { ...identity(row), passwordHash: row.password_hash };
}

function timestamp(value: Date | string, field: string): string {
  const parsed = value instanceof Date ? value : new Date(value);
  if (!Number.isFinite(parsed.getTime())) {
    throw new Error(`authentication ${field} is invalid`);
  }
  return parsed.toISOString();
}

function count(value: unknown, field: string): number {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 0) {
    throw new Error(`authentication ${field} is invalid`);
  }
  return parsed;
}

function sessionSummary(row: AuthSessionSummaryRow): AuthSessionSummaryRecord {
  if (typeof row.session_digest !== "string" || !/^[0-9a-f]{64}$/.test(row.session_digest)) {
    throw new Error("authentication session digest is invalid");
  }
  return {
    sessionDigest: row.session_digest,
    createdAt: timestamp(row.created_at, "created_at"),
    lastSeenAt: timestamp(row.last_seen_at, "last_seen_at"),
    idleExpiresAt: timestamp(row.idle_expires_at, "idle_expires_at"),
    absoluteExpiresAt: timestamp(row.absolute_expires_at, "absolute_expires_at"),
  };
}

export class PostgresAuthRepository implements AuthRepository, OnModuleDestroy {
  constructor(private readonly pool: Pool) {}

  async findUserByUsername(username: string): Promise<AuthUserRecord | null> {
    const result = await this.pool.query<AuthUserRow>(
      `SELECT user_id, username, display_name, password_hash, roles, disabled
       FROM auth_users
       WHERE username = $1
       LIMIT 1`,
      [username],
    );
    const row = result.rows[0];
    return row === undefined ? null : user(row);
  }

  async countRecentFailures(usernameDigest: string, since: string): Promise<LoginAttemptCounts> {
    const result = await this.pool.query<{
      username_failures: string | number;
      global_failures: string | number;
    }>(
      `SELECT
         count(*) FILTER (WHERE username_digest = $1) AS username_failures,
         count(*) AS global_failures
       FROM auth_login_attempts
       WHERE attempted_at >= $2::timestamptz AND outcome = 'FAILURE'`,
      [usernameDigest, since],
    );
    const row = result.rows[0];
    if (row === undefined) throw new Error("authentication login-attempt counts are unavailable");
    return {
      usernameFailures: count(row.username_failures, "username failure count"),
      globalFailures: count(row.global_failures, "global failure count"),
    };
  }

  async recordLoginAttempt(
    usernameDigest: string,
    outcome: LoginAttemptOutcome,
    attemptedAt: string,
  ): Promise<void> {
    await this.pool.query(
      `INSERT INTO auth_login_attempts (
         attempt_id, username_digest, attempted_at, outcome
       ) VALUES ($1, $2, $3::timestamptz, $4)`,
      [randomUUID(), usernameDigest, attemptedAt, outcome],
    );
  }

  async createSession(session: NewAuthSession): Promise<void> {
    await this.pool.query(
      `INSERT INTO auth_sessions (
         session_digest, user_id, created_at, last_seen_at,
         idle_expires_at, absolute_expires_at, revoked_at
       ) VALUES ($1, $2, $3::timestamptz, $4::timestamptz, $5::timestamptz, $6::timestamptz, NULL)`,
      [
        session.sessionDigest,
        session.userId,
        session.createdAt,
        session.lastSeenAt,
        session.idleExpiresAt,
        session.absoluteExpiresAt,
      ],
    );
  }

  async findSession(sessionDigest: string): Promise<AuthSessionRecord | null> {
    const result = await this.pool.query<AuthSessionRow>(
      `SELECT session.session_digest, session.created_at, session.last_seen_at,
              session.idle_expires_at, session.absolute_expires_at, session.revoked_at,
              account.user_id, account.username, account.display_name,
              account.roles, account.disabled
       FROM auth_sessions AS session
       INNER JOIN auth_users AS account ON account.user_id = session.user_id
       WHERE session.session_digest = $1
       LIMIT 1`,
      [sessionDigest],
    );
    const row = result.rows[0];
    if (row === undefined) return null;
    return {
      ...identity(row),
      sessionDigest: row.session_digest,
      createdAt: timestamp(row.created_at, "created_at"),
      lastSeenAt: timestamp(row.last_seen_at, "last_seen_at"),
      idleExpiresAt: timestamp(row.idle_expires_at, "idle_expires_at"),
      absoluteExpiresAt: timestamp(row.absolute_expires_at, "absolute_expires_at"),
      revokedAt: row.revoked_at === null ? null : timestamp(row.revoked_at, "revoked_at"),
    };
  }

  async touchSession(
    sessionDigest: string,
    lastSeenAt: string,
    idleExpiresAt: string,
  ): Promise<boolean> {
    const result = await this.pool.query(
      `UPDATE auth_sessions
       SET last_seen_at = GREATEST(last_seen_at, $2::timestamptz),
           idle_expires_at = LEAST(
             absolute_expires_at,
             GREATEST(idle_expires_at, $3::timestamptz)
           )
       WHERE session_digest = $1
         AND revoked_at IS NULL
         AND idle_expires_at > $2::timestamptz
         AND absolute_expires_at > $2::timestamptz`,
      [sessionDigest, lastSeenAt, idleExpiresAt],
    );
    return result.rowCount === 1;
  }

  async revokeSession(sessionDigest: string, revokedAt = new Date().toISOString()): Promise<void> {
    await this.pool.query(
      `UPDATE auth_sessions
       SET revoked_at = COALESCE(revoked_at, $2::timestamptz)
       WHERE session_digest = $1`,
      [sessionDigest, revokedAt],
    );
  }

  async listActiveSessions(userId: string, asOf: string): Promise<AuthSessionSummaryRecord[]> {
    const result = await this.pool.query<AuthSessionSummaryRow>(
      `SELECT session_digest, created_at, last_seen_at, idle_expires_at, absolute_expires_at
       FROM auth_sessions
       WHERE user_id = $1
         AND revoked_at IS NULL
         AND idle_expires_at > $2::timestamptz
         AND absolute_expires_at > $2::timestamptz
       ORDER BY last_seen_at DESC, created_at DESC
       LIMIT 64`,
      [userId, asOf],
    );
    return result.rows.map(sessionSummary);
  }

  async replacePasswordAndRevokeOtherSessions(
    userId: string,
    currentSessionDigest: string,
    passwordHash: string,
    changedAt: string,
  ): Promise<PasswordChangeCommit> {
    const result = await this.pool.query<{
      password_updated: boolean;
      revoked_sessions: string | number;
    }>(
      `WITH changed AS (
         UPDATE auth_users
         SET password_hash = $3, updated_at = $4::timestamptz
         WHERE user_id = $1
           AND disabled = FALSE
           AND EXISTS (
             SELECT 1
             FROM auth_sessions AS current_session
             WHERE current_session.user_id = auth_users.user_id
               AND current_session.session_digest = $2
               AND current_session.revoked_at IS NULL
               AND current_session.idle_expires_at > $4::timestamptz
               AND current_session.absolute_expires_at > $4::timestamptz
           )
         RETURNING user_id
       ), revoked AS (
         UPDATE auth_sessions
         SET revoked_at = COALESCE(revoked_at, $4::timestamptz)
         WHERE user_id = (SELECT user_id FROM changed)
           AND session_digest <> $2
           AND revoked_at IS NULL
         RETURNING session_digest
       )
       SELECT EXISTS(SELECT 1 FROM changed) AS password_updated,
              count(*) AS revoked_sessions
       FROM revoked`,
      [userId, currentSessionDigest, passwordHash, changedAt],
    );
    const row = result.rows[0];
    if (row === undefined || typeof row.password_updated !== "boolean") {
      throw new Error("authentication password change result is invalid");
    }
    return {
      passwordUpdated: row.password_updated,
      revokedSessions: count(row.revoked_sessions, "revoked session count"),
    };
  }

  async revokeUserSession(
    userId: string,
    sessionDigest: string,
    currentSessionDigest: string,
    revokedAt: string,
  ): Promise<boolean> {
    const result = await this.pool.query(
      `UPDATE auth_sessions
       SET revoked_at = COALESCE(revoked_at, $4::timestamptz)
       WHERE user_id = $1
         AND session_digest = $2
         AND session_digest <> $3
         AND revoked_at IS NULL
         AND idle_expires_at > $4::timestamptz
         AND absolute_expires_at > $4::timestamptz`,
      [userId, sessionDigest, currentSessionDigest, revokedAt],
    );
    return result.rowCount === 1;
  }

  async onModuleDestroy(): Promise<void> {
    await this.pool.end();
  }
}
