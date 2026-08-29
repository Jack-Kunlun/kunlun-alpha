import { UnauthorizedException } from "@nestjs/common";
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
  verifyCalls = 0;

  async hash(): Promise<string> {
    return "unused";
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
});
