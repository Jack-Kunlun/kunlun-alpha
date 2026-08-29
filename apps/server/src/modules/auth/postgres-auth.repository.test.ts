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
});
