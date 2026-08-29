import { BadRequestException, ForbiddenException, UnauthorizedException } from "@nestjs/common";
import { describe, expect, it } from "vitest";
import type { PasswordHasher } from "./password";
import { AuthService } from "./auth.service";
import type {
  AuthRepository,
  AuthSessionRecord,
  AuthUserRecord,
  LoginAttemptCounts,
  NewAuthSession,
} from "./auth.types";

const now = new Date("2026-08-29T08:00:00.000Z");
const user: AuthUserRecord = {
  userId: "9b596d16-8aae-4a10-8aa7-88c8c9f7458e",
  username: "admin",
  displayName: "本地管理员",
  passwordHash: "stored-password-hash",
  roles: ["platform_admin"],
  disabled: false,
};

class FakeHasher implements PasswordHasher {
  dummyCalls = 0;
  hashCalls: string[] = [];
  verifyCalls = 0;

  async hash(password: string): Promise<string> {
    this.hashCalls.push(password);
    return "new-password-hash";
  }

  async verify(password: string, encoded: string): Promise<boolean> {
    this.verifyCalls += 1;
    return password === "correct password value" && encoded === user.passwordHash;
  }

  async consumeDummy(): Promise<void> {
    this.dummyCalls += 1;
  }
}

class FakeRepository implements AuthRepository {
  attempts: Array<{ usernameDigest: string; outcome: string }> = [];
  createdSession: NewAuthSession | null = null;
  counts: LoginAttemptCounts = { usernameFailures: 0, globalFailures: 0 };
  storedUser: AuthUserRecord | null = user;
  storedSession: AuthSessionRecord | null = null;
  touches: Array<{ sessionDigest: string; lastSeenAt: string; idleExpiresAt: string }> = [];
  revoked: string[] = [];
  activeSessions: Array<{
    sessionDigest: string;
    createdAt: string;
    lastSeenAt: string;
    idleExpiresAt: string;
    absoluteExpiresAt: string;
  }> = [];
  passwordChanges: Array<{
    userId: string;
    currentSessionDigest: string;
    passwordHash: string;
    changedAt: string;
  }> = [];
  managedRevocations: Array<{
    userId: string;
    sessionDigest: string;
    currentSessionDigest: string;
    revokedAt: string;
  }> = [];

  async findUserByUsername(): Promise<AuthUserRecord | null> {
    return this.storedUser;
  }

  async countRecentFailures(): Promise<LoginAttemptCounts> {
    return this.counts;
  }

  async recordLoginAttempt(usernameDigest: string, outcome: string): Promise<void> {
    this.attempts.push({ usernameDigest, outcome });
  }

  async createSession(session: NewAuthSession): Promise<void> {
    this.createdSession = session;
  }

  async findSession(): Promise<AuthSessionRecord | null> {
    return this.storedSession;
  }

  async touchSession(
    sessionDigest: string,
    lastSeenAt: string,
    idleExpiresAt: string,
  ): Promise<boolean> {
    this.touches.push({ sessionDigest, lastSeenAt, idleExpiresAt });
    return true;
  }

  async revokeSession(sessionDigest: string): Promise<void> {
    this.revoked.push(sessionDigest);
  }

  async listActiveSessions(): Promise<typeof this.activeSessions> {
    return this.activeSessions;
  }

  async replacePasswordAndRevokeOtherSessions(
    userId: string,
    currentSessionDigest: string,
    passwordHash: string,
    changedAt: string,
  ): Promise<{ passwordUpdated: boolean; revokedSessions: number }> {
    this.passwordChanges.push({ userId, currentSessionDigest, passwordHash, changedAt });
    return { passwordUpdated: true, revokedSessions: 2 };
  }

  async revokeUserSession(
    userId: string,
    sessionDigest: string,
    currentSessionDigest: string,
    revokedAt: string,
  ): Promise<boolean> {
    this.managedRevocations.push({ userId, sessionDigest, currentSessionDigest, revokedAt });
    return true;
  }
}

const config = {
  postgresDsn: "postgresql://local.invalid/kunlun",
  publicOrigin: "http://localhost:5173",
  cookieName: "kunlun_session",
  secureCookie: false,
  idleTimeoutMs: 30 * 60 * 1000,
  absoluteTimeoutMs: 8 * 60 * 60 * 1000,
  loginWindowMs: 15 * 60 * 1000,
  usernameAttemptLimit: 8,
  globalAttemptLimit: 50,
} as const;

describe("AuthService", () => {
  it("creates an opaque durable session and never persists the raw token", async () => {
    const repository = new FakeRepository();
    const hasher = new FakeHasher();
    const service = new AuthService(repository, hasher, config, () => now);

    const result = await service.login(" Admin ", "correct password value");

    expect(result.response.user).toEqual({
      userId: user.userId,
      username: "admin",
      displayName: "本地管理员",
      roles: ["platform_admin"],
    });
    expect(result.sessionToken).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(result.response.csrfToken).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(repository.createdSession?.sessionDigest).toMatch(/^[0-9a-f]{64}$/);
    expect(repository.createdSession?.sessionDigest).not.toContain(result.sessionToken);
    expect(repository.attempts.at(-1)?.outcome).toBe("SUCCESS");
  });

  it("uses the same generic failure for an unknown user after dummy scrypt work", async () => {
    const repository = new FakeRepository();
    repository.storedUser = null;
    const hasher = new FakeHasher();
    const service = new AuthService(repository, hasher, config, () => now);

    await expect(service.login("unknown", "correct password value")).rejects.toEqual(
      new UnauthorizedException("用户名或密码错误"),
    );
    expect(hasher.dummyCalls).toBe(1);
    expect(repository.attempts.at(-1)?.outcome).toBe("FAILURE");
  });

  it("enforces persistent throttling before password work", async () => {
    const repository = new FakeRepository();
    repository.counts = { usernameFailures: 8, globalFailures: 8 };
    const hasher = new FakeHasher();
    const service = new AuthService(repository, hasher, config, () => now);

    await expect(service.login("admin", "correct password value")).rejects.toMatchObject({
      status: 429,
    });
    expect(hasher.verifyCalls).toBe(0);
    expect(repository.attempts.at(-1)?.outcome).toBe("THROTTLED");
  });

  it("authenticates, advances only the idle deadline and verifies the bound CSRF token", async () => {
    const repository = new FakeRepository();
    const hasher = new FakeHasher();
    const service = new AuthService(repository, hasher, config, () => now);
    const login = await service.login("admin", "correct password value");
    const created = repository.createdSession;
    expect(created).not.toBeNull();
    repository.storedSession = {
      ...user,
      sessionDigest: created?.sessionDigest ?? "",
      createdAt: created?.createdAt ?? "",
      lastSeenAt: created?.lastSeenAt ?? "",
      idleExpiresAt: created?.idleExpiresAt ?? "",
      absoluteExpiresAt: created?.absoluteExpiresAt ?? "",
      revokedAt: null,
    };

    const authenticated = await service.authenticate(login.sessionToken);
    expect(authenticated.response.csrfToken).toBe(login.response.csrfToken);
    expect(repository.touches).toHaveLength(1);
    expect(() => service.assertCsrf(login.sessionToken, login.response.csrfToken)).not.toThrow();
    expect(() => service.assertCsrf(login.sessionToken, "x".repeat(43))).toThrow("CSRF");
  });

  it("lists opaque session references and marks only the authenticated session as current", async () => {
    const repository = new FakeRepository();
    repository.activeSessions = [
      {
        sessionDigest: "a".repeat(64),
        createdAt: "2026-08-29T07:00:00.000Z",
        lastSeenAt: "2026-08-29T08:00:00.000Z",
        idleExpiresAt: "2026-08-29T08:30:00.000Z",
        absoluteExpiresAt: "2026-08-29T15:00:00.000Z",
      },
      {
        sessionDigest: "b".repeat(64),
        createdAt: "2026-08-29T06:00:00.000Z",
        lastSeenAt: "2026-08-29T07:50:00.000Z",
        idleExpiresAt: "2026-08-29T08:20:00.000Z",
        absoluteExpiresAt: "2026-08-29T14:00:00.000Z",
      },
    ];
    const service = new AuthService(repository, new FakeHasher(), config, () => now);

    const result = await service.listSessions({
      sessionDigest: "a".repeat(64),
      userId: user.userId,
      username: user.username,
      displayName: user.displayName,
      roles: ["platform_admin"],
      absoluteExpiresAt: "2026-08-29T15:00:00.000Z",
      idleExpiresAt: "2026-08-29T08:30:00.000Z",
      response: {} as never,
    });

    expect(result.schemaVersion).toBe("auth-session-list-v1");
    expect(result.sessions.map((session) => session.current)).toEqual([true, false]);
    expect(result.sessions[0]?.sessionId).toMatch(/^[0-9a-f]{64}$/);
    expect(JSON.stringify(result)).not.toContain("a".repeat(64));
    expect(JSON.stringify(result)).not.toContain("b".repeat(64));
  });

  it("verifies the current password before atomically changing it and revoking other sessions", async () => {
    const repository = new FakeRepository();
    const hasher = new FakeHasher();
    const service = new AuthService(repository, hasher, config, () => now);

    const result = await service.changePassword(
      {
        sessionDigest: "a".repeat(64),
        userId: user.userId,
        username: user.username,
        displayName: user.displayName,
        roles: ["platform_admin"],
        absoluteExpiresAt: "2026-08-29T15:00:00.000Z",
        idleExpiresAt: "2026-08-29T08:30:00.000Z",
        response: {} as never,
      },
      "correct password value",
      "new stronger password value",
    );

    expect(result).toEqual({
      schemaVersion: "auth-password-change-v1",
      changedAt: now.toISOString(),
      revokedOtherSessions: 2,
    });
    expect(hasher.hashCalls).toEqual(["new stronger password value"]);
    expect(repository.passwordChanges).toEqual([
      {
        userId: user.userId,
        currentSessionDigest: "a".repeat(64),
        passwordHash: "new-password-hash",
        changedAt: now.toISOString(),
      },
    ]);
  });

  it("rejects an incorrect or reused current password without changing durable state", async () => {
    const repository = new FakeRepository();
    const hasher = new FakeHasher();
    const service = new AuthService(repository, hasher, config, () => now);
    const session = {
      sessionDigest: "a".repeat(64),
      userId: user.userId,
      username: user.username,
      displayName: user.displayName,
      roles: ["platform_admin"] as ["platform_admin"],
      absoluteExpiresAt: "2026-08-29T15:00:00.000Z",
      idleExpiresAt: "2026-08-29T08:30:00.000Z",
      response: {} as never,
    };

    await expect(
      service.changePassword(session, "incorrect password value", "new stronger password value"),
    ).rejects.toEqual(new ForbiddenException("当前密码错误"));
    await expect(
      service.changePassword(session, "correct password value", "correct password value"),
    ).rejects.toEqual(new BadRequestException("新密码不能与当前密码相同"));
    expect(hasher.hashCalls).toHaveLength(0);
    expect(repository.passwordChanges).toHaveLength(0);
  });

  it("revokes only an opaque non-current session owned by the authenticated user", async () => {
    const repository = new FakeRepository();
    repository.activeSessions = [
      {
        sessionDigest: "a".repeat(64),
        createdAt: "2026-08-29T07:00:00.000Z",
        lastSeenAt: "2026-08-29T08:00:00.000Z",
        idleExpiresAt: "2026-08-29T08:30:00.000Z",
        absoluteExpiresAt: "2026-08-29T15:00:00.000Z",
      },
      {
        sessionDigest: "b".repeat(64),
        createdAt: "2026-08-29T06:00:00.000Z",
        lastSeenAt: "2026-08-29T07:50:00.000Z",
        idleExpiresAt: "2026-08-29T08:20:00.000Z",
        absoluteExpiresAt: "2026-08-29T14:00:00.000Z",
      },
    ];
    const service = new AuthService(repository, new FakeHasher(), config, () => now);
    const session = {
      sessionDigest: "a".repeat(64),
      userId: user.userId,
      username: user.username,
      displayName: user.displayName,
      roles: ["platform_admin"] as ["platform_admin"],
      absoluteExpiresAt: "2026-08-29T15:00:00.000Z",
      idleExpiresAt: "2026-08-29T08:30:00.000Z",
      response: {} as never,
    };
    const listed = await service.listSessions(session);
    const other = listed.sessions.find((candidate) => !candidate.current);
    const current = listed.sessions.find((candidate) => candidate.current);

    await expect(service.revokeManagedSession(session, other?.sessionId ?? "")).resolves.toEqual({
      schemaVersion: "auth-session-revocation-v1",
      revoked: true,
    });
    await expect(service.revokeManagedSession(session, current?.sessionId ?? "")).rejects.toEqual(
      new BadRequestException("当前会话请使用退出登录"),
    );
    expect(repository.managedRevocations).toEqual([
      {
        userId: user.userId,
        sessionDigest: "b".repeat(64),
        currentSessionDigest: "a".repeat(64),
        revokedAt: now.toISOString(),
      },
    ]);
  });
});
