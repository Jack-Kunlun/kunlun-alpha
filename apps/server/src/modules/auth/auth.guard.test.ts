import type { ExecutionContext } from "@nestjs/common";
import { Reflector } from "@nestjs/core";
import { describe, expect, it, vi } from "vitest";
import { AuthenticationGuard } from "./auth.guard";
import type { AuthenticatedRequest } from "./auth.request";
import type { AuthenticatedSession, AuthService } from "./auth.service";
import { PUBLIC_ROUTE_METADATA } from "./public-route.decorator";
import { INTERNAL_SERVICE_ROUTE_METADATA } from "./internal-service-route.decorator";

const config = {
  postgresDsn: "postgresql://local.invalid/kunlun",
  publicOrigin: "http://localhost:5173",
  cookieName: "kunlun_session",
  secureCookie: false,
  idleTimeoutMs: 1,
  absoluteTimeoutMs: 1,
  loginWindowMs: 1,
  usernameAttemptLimit: 1,
  globalAttemptLimit: 1,
};

const session: AuthenticatedSession = {
  sessionDigest: "a".repeat(64),
  userId: "9b596d16-8aae-4a10-8aa7-88c8c9f7458e",
  username: "admin",
  displayName: "本地管理员",
  roles: ["platform_admin"],
  absoluteExpiresAt: "2026-08-29T16:00:00.000Z",
  idleExpiresAt: "2026-08-29T08:30:00.000Z",
  response: {
    schemaVersion: "auth-session-v1",
    authenticated: true,
    user: {
      userId: "9b596d16-8aae-4a10-8aa7-88c8c9f7458e",
      username: "admin",
      displayName: "本地管理员",
      roles: ["platform_admin"],
    },
    csrfToken: "c".repeat(43),
    absoluteExpiresAt: "2026-08-29T16:00:00.000Z",
    idleExpiresAt: "2026-08-29T08:30:00.000Z",
  },
};

function context(
  request: Partial<AuthenticatedRequest>,
  isPublic = false,
  internalService = false,
): ExecutionContext {
  const handler = () => undefined;
  if (isPublic) Reflect.defineMetadata(PUBLIC_ROUTE_METADATA, true, handler);
  if (internalService) {
    Reflect.defineMetadata(INTERNAL_SERVICE_ROUTE_METADATA, "market-data-settings", handler);
  }
  return {
    switchToHttp: () => ({ getRequest: () => request }),
    getHandler: () => handler,
    getClass: () => class TestController {},
  } as unknown as ExecutionContext;
}

describe("AuthenticationGuard", () => {
  it("keeps public health-style GET routes available without a session", async () => {
    const auth = { authenticate: vi.fn(), assertCsrf: vi.fn() } as unknown as AuthService;
    const guard = new AuthenticationGuard(new Reflector(), auth, config);
    await expect(guard.canActivate(context({ method: "GET", headers: {} }, true))).resolves.toBe(
      true,
    );
    expect(auth.authenticate).not.toHaveBeenCalled();
  });

  it("authenticates protected requests and requires origin plus CSRF for writes", async () => {
    const authenticate = vi.fn().mockResolvedValue(session);
    const assertCsrf = vi.fn();
    const auth = { authenticate, assertCsrf } as unknown as AuthService;
    const guard = new AuthenticationGuard(new Reflector(), auth, config);
    const token = "s".repeat(43);
    const request = {
      method: "POST",
      headers: {
        cookie: `kunlun_session=${token}`,
        origin: "http://localhost:5173",
        "sec-fetch-site": "same-origin",
        "x-csrf-token": "c".repeat(43),
      },
    } as Partial<AuthenticatedRequest>;

    await expect(guard.canActivate(context(request))).resolves.toBe(true);
    expect(authenticate).toHaveBeenCalledWith(token);
    expect(assertCsrf).toHaveBeenCalledWith(token, "c".repeat(43));
    expect(request.authSession).toBe(session);
  });

  it("fails closed when a protected request lacks the opaque cookie", async () => {
    const auth = { authenticate: vi.fn(), assertCsrf: vi.fn() } as unknown as AuthService;
    const guard = new AuthenticationGuard(new Reflector(), auth, config);
    await expect(guard.canActivate(context({ method: "GET", headers: {} }))).rejects.toMatchObject({
      status: 401,
    });
  });

  it("authenticates only the dedicated internal settings route with a bearer secret", async () => {
    const auth = { authenticate: vi.fn(), assertCsrf: vi.fn() } as unknown as AuthService;
    const guard = new AuthenticationGuard(new Reflector(), auth, {
      ...config,
      marketDataSettingsWorkerToken: "w".repeat(32),
    });
    const request = {
      method: "GET",
      url: "/api/v1/internal/market-data/settings",
      originalUrl: "/api/v1/internal/market-data/settings",
      headers: { authorization: `Bearer ${"w".repeat(32)}` },
    } as Partial<AuthenticatedRequest>;

    await expect(guard.canActivate(context(request, false, true))).resolves.toBe(true);
    expect(auth.authenticate).not.toHaveBeenCalled();
  });

  it("rejects browser cookies and metadata on the internal settings route", async () => {
    const auth = { authenticate: vi.fn(), assertCsrf: vi.fn() } as unknown as AuthService;
    const guard = new AuthenticationGuard(new Reflector(), auth, {
      ...config,
      marketDataSettingsWorkerToken: "w".repeat(32),
    });
    await expect(
      guard.canActivate(
        context(
          {
            method: "GET",
            url: "/api/v1/internal/market-data/settings",
            originalUrl: "/api/v1/internal/market-data/settings",
            headers: {
              authorization: `Bearer ${"w".repeat(32)}`,
              cookie: `kunlun_session=${"s".repeat(43)}`,
              origin: "http://localhost:5173",
            },
          },
          false,
          true,
        ),
      ),
    ).rejects.toMatchObject({ status: 401 });
  });
});
