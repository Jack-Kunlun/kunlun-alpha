import type { Pool } from "pg";
import { describe, expect, it, vi } from "vitest";
import { PostgresAuthRepository } from "./postgres-auth.repository";

describe("PostgresAuthRepository", () => {
  it("loads only a validated platform administrator record", async () => {
    const query = vi.fn().mockResolvedValue({
      rows: [
        {
          user_id: "9b596d16-8aae-4a10-8aa7-88c8c9f7458e",
          username: "admin",
          display_name: "本地管理员",
          password_hash: "$scrypt$v=1$hash",
          roles: ["platform_admin"],
          disabled: false,
        },
      ],
      rowCount: 1,
    });
    const repository = new PostgresAuthRepository({ query } as unknown as Pool);

    await expect(repository.findUserByUsername("admin")).resolves.toMatchObject({
      username: "admin",
      roles: ["platform_admin"],
    });
    expect(query.mock.calls[0]?.[0]).toContain("WHERE username = $1");
    expect(query.mock.calls[0]?.[1]).toEqual(["admin"]);
  });

  it("fails closed when session renewal loses a revocation or expiry race", async () => {
    const query = vi.fn().mockResolvedValue({ rows: [], rowCount: 0 });
    const repository = new PostgresAuthRepository({ query } as unknown as Pool);

    await expect(
      repository.touchSession(
        "a".repeat(64),
        "2026-08-29T08:00:00.000Z",
        "2026-08-29T08:30:00.000Z",
      ),
    ).resolves.toBe(false);
    expect(query.mock.calls[0]?.[0]).toContain("revoked_at IS NULL");
    expect(query.mock.calls[0]?.[0]).toContain("absolute_expires_at >");
  });

  it("does not load a password hash while resolving an existing session", async () => {
    const query = vi.fn().mockResolvedValue({
      rows: [
        {
          session_digest: "a".repeat(64),
          created_at: "2026-08-29T08:00:00.000Z",
          last_seen_at: "2026-08-29T08:00:00.000Z",
          idle_expires_at: "2026-08-29T08:30:00.000Z",
          absolute_expires_at: "2026-08-29T16:00:00.000Z",
          revoked_at: null,
          user_id: "9b596d16-8aae-4a10-8aa7-88c8c9f7458e",
          username: "admin",
          display_name: "本地管理员",
          roles: ["platform_admin"],
          disabled: false,
        },
      ],
      rowCount: 1,
    });
    const repository = new PostgresAuthRepository({ query } as unknown as Pool);

    await expect(repository.findSession("a".repeat(64))).resolves.toMatchObject({
      username: "admin",
      sessionDigest: "a".repeat(64),
    });
    expect(query.mock.calls[0]?.[0]).not.toContain("password_hash");
  });

  it("lists only active sessions owned by the authenticated user", async () => {
    const query = vi.fn().mockResolvedValue({
      rows: [
        {
          session_digest: "a".repeat(64),
          created_at: "2026-08-29T08:00:00.000Z",
          last_seen_at: "2026-08-29T08:05:00.000Z",
          idle_expires_at: "2026-08-29T08:35:00.000Z",
          absolute_expires_at: "2026-08-29T16:00:00.000Z",
        },
      ],
      rowCount: 1,
    });
    const repository = new PostgresAuthRepository({ query } as unknown as Pool);

    await expect(
      repository.listActiveSessions(
        "9b596d16-8aae-4a10-8aa7-88c8c9f7458e",
        "2026-08-29T08:10:00.000Z",
      ),
    ).resolves.toHaveLength(1);
    expect(query.mock.calls[0]?.[0]).toContain("WHERE user_id = $1");
    expect(query.mock.calls[0]?.[0]).toContain("revoked_at IS NULL");
    expect(query.mock.calls[0]?.[0]).toContain("idle_expires_at > $2");
    expect(query.mock.calls[0]?.[0]).toContain("LIMIT 64");
    expect(query.mock.calls[0]?.[0]).not.toContain("password_hash");
  });

  it("changes the password and revokes other sessions in one SQL statement", async () => {
    const query = vi.fn().mockResolvedValue({
      rows: [{ password_updated: true, revoked_sessions: "2" }],
      rowCount: 1,
    });
    const repository = new PostgresAuthRepository({ query } as unknown as Pool);

    await expect(
      repository.replacePasswordAndRevokeOtherSessions(
        "9b596d16-8aae-4a10-8aa7-88c8c9f7458e",
        "a".repeat(64),
        "$scrypt$v=1$new-password-hash",
        "2026-08-29T08:10:00.000Z",
      ),
    ).resolves.toEqual({ passwordUpdated: true, revokedSessions: 2 });
    expect(query).toHaveBeenCalledTimes(1);
    expect(query.mock.calls[0]?.[0]).toContain("WITH changed AS");
    expect(query.mock.calls[0]?.[0]).toContain("session_digest <> $2");
    expect(query.mock.calls[0]?.[0]).toContain("disabled = FALSE");
    expect(query.mock.calls[0]?.[0]).toContain("current_session.session_digest = $2");
    expect(query.mock.calls[0]?.[0]).toContain("current_session.revoked_at IS NULL");
  });

  it("scopes managed revocation to the user and excludes the current session", async () => {
    const query = vi.fn().mockResolvedValue({ rows: [], rowCount: 1 });
    const repository = new PostgresAuthRepository({ query } as unknown as Pool);

    await expect(
      repository.revokeUserSession(
        "9b596d16-8aae-4a10-8aa7-88c8c9f7458e",
        "b".repeat(64),
        "a".repeat(64),
        "2026-08-29T08:10:00.000Z",
      ),
    ).resolves.toBe(true);
    expect(query.mock.calls[0]?.[0]).toContain("user_id = $1");
    expect(query.mock.calls[0]?.[0]).toContain("session_digest = $2");
    expect(query.mock.calls[0]?.[0]).toContain("session_digest <> $3");
    expect(query.mock.calls[0]?.[0]).toContain("absolute_expires_at > $4");
  });
});
