import type { AuthSessionResponse } from "@kunlun/shared-types";
import {
  ForbiddenException,
  HttpException,
  Inject,
  Injectable,
  Optional,
  ServiceUnavailableException,
  UnauthorizedException,
} from "@nestjs/common";
import { createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import type { AuthConfig } from "./auth.config";
import { normalizeUsername, type PasswordHasher, validatePassword } from "./password";
import type {
  AuthRepository,
  AuthUserIdentityRecord,
  LoginAttemptOutcome,
  NewAuthSession,
} from "./auth.types";
import { AUTH_CONFIG, AUTH_PASSWORD_HASHER, AUTH_REPOSITORY } from "./auth.tokens";

const SESSION_TOKEN = /^[A-Za-z0-9_-]{43}$/;
const CSRF_TOKEN = /^[A-Za-z0-9_-]{43}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export interface AuthLoginResult {
  sessionToken: string;
  response: AuthSessionResponse;
}

export interface AuthenticatedSession {
  sessionDigest: string;
  userId: string;
  username: string;
  displayName: string;
  roles: ["platform_admin"];
  absoluteExpiresAt: string;
  idleExpiresAt: string;
  response: AuthSessionResponse;
}

type Clock = () => Date;

function sha256(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function csrfForSession(sessionToken: string): string {
  return createHmac("sha256", sessionToken)
    .update("kunlun-auth-csrf-v1", "utf8")
    .digest("base64url");
}

function iso(value: number): string {
  return new Date(value).toISOString();
}

function validUser(user: AuthUserIdentityRecord): boolean {
  return (
    UUID.test(user.userId) &&
    user.username === normalizeUsername(user.username) &&
    user.displayName.length >= 1 &&
    user.displayName.length <= 80 &&
    user.roles.length === 1 &&
    user.roles[0] === "platform_admin"
  );
}

function finiteInstant(value: string): number {
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) throw new Error("authentication session contains an invalid time");
  return parsed;
}

@Injectable()
export class AuthService {
  constructor(
    @Inject(AUTH_REPOSITORY)
    private readonly repository: AuthRepository,
    @Inject(AUTH_PASSWORD_HASHER)
    private readonly passwordHasher: PasswordHasher,
    @Inject(AUTH_CONFIG)
    private readonly config: AuthConfig,
    @Optional()
    private readonly clock: Clock = () => new Date(),
  ) {}

  async login(rawUsername: string, password: string): Promise<AuthLoginResult> {
    const attemptedAt = this.now();
    let username: string | null = null;
    try {
      username = normalizeUsername(rawUsername);
    } catch {
      username = null;
    }
    const usernameDigest = sha256(username ?? `invalid:${rawUsername.slice(0, 128)}`);
    const since = iso(attemptedAt.getTime() - this.config.loginWindowMs);
    const counts = await this.repository.countRecentFailures(usernameDigest, since);
    if (
      counts.usernameFailures >= this.config.usernameAttemptLimit ||
      counts.globalFailures >= this.config.globalAttemptLimit
    ) {
      await this.recordAttempt(usernameDigest, "THROTTLED", attemptedAt);
      throw new HttpException("登录暂时受限，请稍后重试", 429);
    }

    const user = username === null ? null : await this.repository.findUserByUsername(username);
    let passwordShapeValid = true;
    try {
      validatePassword(password);
    } catch {
      passwordShapeValid = false;
    }

    let verified = false;
    try {
      if (passwordShapeValid && user !== null && !user.disabled) {
        verified = await this.passwordHasher.verify(password, user.passwordHash);
      } else {
        await this.passwordHasher.consumeDummy(password);
      }
    } catch {
      throw new ServiceUnavailableException("登录验证资源暂时不可用");
    }

    if (!verified || user === null || user.disabled || !validUser(user)) {
      await this.recordAttempt(usernameDigest, "FAILURE", attemptedAt);
      throw new UnauthorizedException("用户名或密码错误");
    }

    const sessionToken = randomBytes(32).toString("base64url");
    const sessionDigest = sha256(sessionToken);
    const absoluteExpiresAt = iso(attemptedAt.getTime() + this.config.absoluteTimeoutMs);
    const idleExpiresAt = iso(attemptedAt.getTime() + this.config.idleTimeoutMs);
    const session: NewAuthSession = {
      sessionDigest,
      userId: user.userId,
      createdAt: attemptedAt.toISOString(),
      lastSeenAt: attemptedAt.toISOString(),
      idleExpiresAt,
      absoluteExpiresAt,
    };
    await this.repository.createSession(session);
    await this.recordAttempt(usernameDigest, "SUCCESS", attemptedAt);
    return {
      sessionToken,
      response: this.response(user, sessionToken, absoluteExpiresAt, idleExpiresAt),
    };
  }

  async authenticate(sessionToken: string): Promise<AuthenticatedSession> {
    if (!SESSION_TOKEN.test(sessionToken)) throw new UnauthorizedException("请先登录");
    const sessionDigest = sha256(sessionToken);
    const record = await this.repository.findSession(sessionDigest);
    if (record === null || record.revokedAt !== null || record.disabled || !validUser(record)) {
      throw new UnauthorizedException("登录会话无效或已过期");
    }

    const now = this.now();
    const nowMs = now.getTime();
    const idleExpiry = finiteInstant(record.idleExpiresAt);
    const absoluteExpiry = finiteInstant(record.absoluteExpiresAt);
    finiteInstant(record.createdAt);
    finiteInstant(record.lastSeenAt);
    if (idleExpiry <= nowMs || absoluteExpiry <= nowMs) {
      throw new UnauthorizedException("登录会话无效或已过期");
    }
    const nextIdleExpiry = Math.min(absoluteExpiry, nowMs + this.config.idleTimeoutMs);
    const idleExpiresAt = iso(nextIdleExpiry);
    const touched = await this.repository.touchSession(
      sessionDigest,
      now.toISOString(),
      idleExpiresAt,
    );
    if (!touched) throw new UnauthorizedException("登录会话无效或已过期");
    const response = this.response(
      record,
      sessionToken,
      new Date(absoluteExpiry).toISOString(),
      idleExpiresAt,
    );
    return {
      sessionDigest,
      userId: record.userId,
      username: record.username,
      displayName: record.displayName,
      roles: ["platform_admin"],
      absoluteExpiresAt: response.absoluteExpiresAt,
      idleExpiresAt: response.idleExpiresAt,
      response,
    };
  }

  assertCsrf(sessionToken: string, presentedToken: string | undefined): void {
    const expected = Buffer.from(csrfForSession(sessionToken), "base64url");
    const presented = CSRF_TOKEN.test(presentedToken ?? "")
      ? Buffer.from(presentedToken ?? "", "base64url")
      : Buffer.alloc(expected.length);
    if (presented.length !== expected.length || !timingSafeEqual(presented, expected)) {
      throw new ForbiddenException("CSRF 验证失败");
    }
  }

  async logout(sessionDigest: string): Promise<void> {
    await this.repository.revokeSession(sessionDigest, this.now().toISOString());
  }

  private response(
    user: AuthUserIdentityRecord,
    sessionToken: string,
    absoluteExpiresAt: string,
    idleExpiresAt: string,
  ): AuthSessionResponse {
    return {
      schemaVersion: "auth-session-v1",
      authenticated: true,
      user: {
        userId: user.userId,
        username: user.username,
        displayName: user.displayName,
        roles: ["platform_admin"],
      },
      csrfToken: csrfForSession(sessionToken),
      absoluteExpiresAt,
      idleExpiresAt,
    };
  }

  private async recordAttempt(
    usernameDigest: string,
    outcome: LoginAttemptOutcome,
    attemptedAt: Date,
  ): Promise<void> {
    await this.repository.recordLoginAttempt(usernameDigest, outcome, attemptedAt.toISOString());
  }

  private now(): Date {
    const value = this.clock();
    if (!Number.isFinite(value.getTime())) throw new Error("authentication clock is invalid");
    return value;
  }
}
