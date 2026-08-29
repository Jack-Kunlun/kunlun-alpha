import { randomUUID } from "node:crypto";
import { MigrationRunner, PostgresSqlDriver } from "@kunlun/db";
import { Pool } from "pg";
import { describe, expect, it } from "vitest";
import { migrations } from "../../migrations";
import { PostgresAuthRepository } from "./postgres-auth.repository";

const dsn = process.env["KUNLUN_TEST_POSTGRES_DSN"];
const run = dsn ? describe : describe.skip;
const userId = "9b596d16-8aae-4a10-8aa7-88c8c9f7458e";
const oldHash = `$scrypt$v=1$N=131072,r=8,p=1$${"a".repeat(22)}$${"b".repeat(86)}`;
const newHash = `$scrypt$v=1$N=131072,r=8,p=1$${"c".repeat(22)}$${"d".repeat(86)}`;

run("authentication management PostgreSQL integration", () => {
  it("atomically changes the password while preserving only the current session", async () => {
    const schema = `auth_test_${randomUUID().replaceAll("-", "")}`;
    await createSchema(schema);
    const options = `-c search_path="${schema}"`;
    const driver = new PostgresSqlDriver({ connectionString: dsn, options });
    const pool = new Pool({ connectionString: dsn, options });
    const repository = new PostgresAuthRepository(pool);
    try {
      await new MigrationRunner(driver).migrate(migrations);
      await pool.query(
        `INSERT INTO auth_users (
           user_id, username, display_name, password_hash, roles,
           disabled, created_at, updated_at
         ) VALUES ($1, 'admin', '本地管理员', $2, '["platform_admin"]'::jsonb,
                   FALSE, '2026-08-29T07:00:00Z', '2026-08-29T07:00:00Z')`,
        [userId, oldHash],
      );
      await insertSession(pool, "a".repeat(64), "2026-08-29T08:09:00Z");
      await insertSession(pool, "b".repeat(64), "2026-08-29T08:08:00Z");

      await expect(
        repository.listActiveSessions(userId, "2026-08-29T08:10:00Z"),
      ).resolves.toHaveLength(2);
      await expect(
        repository.replacePasswordAndRevokeOtherSessions(
          userId,
          "a".repeat(64),
          newHash,
          "2026-08-29T08:10:00Z",
        ),
      ).resolves.toEqual({ passwordUpdated: true, revokedSessions: 1 });

      const state = await pool.query<{
        password_hash: string;
        session_digest: string;
        revoked_at: Date | null;
      }>(
        `SELECT account.password_hash, session.session_digest, session.revoked_at
         FROM auth_users AS account
         INNER JOIN auth_sessions AS session ON session.user_id = account.user_id
         WHERE account.user_id = $1
         ORDER BY session.session_digest`,
        [userId],
      );
      expect(state.rows.map((row) => row.password_hash)).toEqual([newHash, newHash]);
      expect(state.rows[0]?.revoked_at).toBeNull();
      expect(state.rows[1]?.revoked_at).toBeInstanceOf(Date);

      await pool.query(
        "UPDATE auth_sessions SET revoked_at = '2026-08-29T08:11:00Z' WHERE session_digest = $1",
        ["a".repeat(64)],
      );
      await expect(
        repository.replacePasswordAndRevokeOtherSessions(
          userId,
          "a".repeat(64),
          oldHash,
          "2026-08-29T08:12:00Z",
        ),
      ).resolves.toEqual({ passwordUpdated: false, revokedSessions: 0 });
      await expect(
        pool.query<{ password_hash: string }>(
          "SELECT password_hash FROM auth_users WHERE user_id = $1",
          [userId],
        ),
      ).resolves.toMatchObject({ rows: [{ password_hash: newHash }] });
    } finally {
      await repository.onModuleDestroy();
      await driver.close();
      await dropSchema(schema);
    }
  });
});

async function insertSession(pool: Pool, digest: string, lastSeenAt: string): Promise<void> {
  await pool.query(
    `INSERT INTO auth_sessions (
       session_digest, user_id, created_at, last_seen_at, idle_expires_at,
       absolute_expires_at, revoked_at
     ) VALUES ($1, $2, '2026-08-29T07:30:00Z', $3::timestamptz,
               '2026-08-29T08:40:00Z', '2026-08-29T16:00:00Z', NULL)`,
    [digest, userId, lastSeenAt],
  );
}

async function createSchema(schema: string): Promise<void> {
  if (!dsn) throw new Error("KUNLUN_TEST_POSTGRES_DSN is required");
  const pool = new Pool({ connectionString: dsn });
  try {
    await pool.query(`CREATE SCHEMA "${schema}"`);
  } finally {
    await pool.end();
  }
}

async function dropSchema(schema: string): Promise<void> {
  if (!dsn) throw new Error("KUNLUN_TEST_POSTGRES_DSN is required");
  const pool = new Pool({ connectionString: dsn });
  try {
    await pool.query(`DROP SCHEMA "${schema}" CASCADE`);
  } finally {
    await pool.end();
  }
}
