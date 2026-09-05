import { Controller, Get, Module, UnauthorizedException, ForbiddenException } from "@nestjs/common";
import { APP_GUARD } from "@nestjs/core";
import { NestFactory } from "@nestjs/core";
import type { INestApplication } from "@nestjs/common";
import { randomBytes } from "node:crypto";
import { ServerResponse, type IncomingMessage, type Server } from "node:http";
import { Readable } from "node:stream";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { AuthenticationGuard } from "../auth/auth.guard";
import type { AuthConfig } from "../auth/auth.config";
import type { AuthenticatedSession } from "../auth/auth.service";
import { AuthService } from "../auth/auth.service";
import { AUTH_CONFIG } from "../auth/auth.tokens";
import {
  MarketDataSettingsController,
  MarketDataSettingsInternalController,
} from "./market-data-settings.controller";
import { encryptToken } from "./market-data-settings.crypto";
import { MarketDataSettingsService } from "./market-data-settings.service";
import {
  MARKET_DATA_SETTINGS_KEY_PROVIDER,
  MARKET_DATA_SETTINGS_REPOSITORY,
} from "./market-data-settings.tokens";
import type {
  MarketDataSettingsKeyProvider,
  MarketDataSettingsRepository,
  PersistedMarketDataSettings,
} from "./market-data-settings.types";

const ADMIN_ID = "9b596d16-8aae-4a10-8aa7-88c8c9f7458e";
const VIEWER_ID = "3f6b7f44-7a16-4df1-a4be-9c8f7fc5db7a";
const ADMIN_COOKIE = "a".repeat(43);
const VIEWER_COOKIE = "b".repeat(43);
const WORKER_TOKEN = "W".repeat(32);
const PUBLIC_ORIGIN = "http://localhost:5173";

@Controller("normal")
class ProtectedProbeController {
  @Get()
  get(): { ok: true } {
    return { ok: true };
  }
}

interface TestApp {
  app: INestApplication;
  server: Server;
  auth: {
    authenticate: ReturnType<typeof vi.fn>;
    assertCsrf: ReturnType<typeof vi.fn>;
  };
}

function authConfig(workerToken: string | undefined): AuthConfig {
  return {
    postgresDsn: "postgresql://unused.test/unused",
    publicOrigin: PUBLIC_ORIGIN,
    cookieName: "__Host-kunlun_session",
    secureCookie: true,
    idleTimeoutMs: 30 * 60 * 1000,
    absoluteTimeoutMs: 8 * 60 * 60 * 1000,
    loginWindowMs: 15 * 60 * 1000,
    usernameAttemptLimit: 8,
    globalAttemptLimit: 50,
    marketDataSettingsWorkerToken: workerToken,
  };
}

function session(userId: string, roles: readonly string[]): AuthenticatedSession {
  return {
    sessionDigest: userId.replaceAll("-", "").padEnd(64, "0").slice(0, 64),
    userId,
    username: "integration-user",
    displayName: "Integration User",
    roles: roles as ["platform_admin"],
    absoluteExpiresAt: "2099-01-01T00:00:00.000Z",
    idleExpiresAt: "2099-01-01T00:00:00.000Z",
    response: {
      schemaVersion: "auth-session-v1",
      user: {
        userId,
        username: "integration-user",
        displayName: "Integration User",
        roles,
      },
      absoluteExpiresAt: "2099-01-01T00:00:00.000Z",
      idleExpiresAt: "2099-01-01T00:00:00.000Z",
    } as never,
  };
}

function repository(initial: PersistedMarketDataSettings | null): MarketDataSettingsRepository {
  let current = initial;
  return {
    get: vi.fn(async () => current),
    compareAndSet: vi.fn(async (input) => {
      current = {
        provider: input.provider,
        revision: input.expectedRevision + 1,
        tokenEnvelope: input.tokenEnvelope,
        updatedAt: input.updatedAt,
      };
      return current;
    }),
  };
}

async function createTestApp(
  settings: PersistedMarketDataSettings | null,
  keyProvider: MarketDataSettingsKeyProvider,
  workerToken: string | undefined,
): Promise<TestApp> {
  const repo = repository(settings);
  const auth = {
    authenticate: vi.fn(async (token: string) => {
      if (token === ADMIN_COOKIE) return session(ADMIN_ID, ["platform_admin"]);
      if (token === VIEWER_COOKIE) return session(VIEWER_ID, ["viewer"]);
      throw new UnauthorizedException("invalid session");
    }),
    assertCsrf: vi.fn((token: string, csrf: string | undefined) => {
      if (token !== ADMIN_COOKIE || csrf !== "csrf-ok") {
        throw new ForbiddenException("invalid csrf");
      }
    }),
  };

  @Module({
    controllers: [
      MarketDataSettingsController,
      MarketDataSettingsInternalController,
      ProtectedProbeController,
    ],
    providers: [
      { provide: MARKET_DATA_SETTINGS_REPOSITORY, useValue: repo },
      { provide: MARKET_DATA_SETTINGS_KEY_PROVIDER, useValue: keyProvider },
      MarketDataSettingsService,
      { provide: AUTH_CONFIG, useValue: authConfig(workerToken) },
      { provide: AuthService, useValue: auth },
      { provide: APP_GUARD, useClass: AuthenticationGuard },
    ],
  })
  class MarketDataSettingsHttpTestModule {}

  const app = await NestFactory.create(MarketDataSettingsHttpTestModule, { logger: false });
  app.setGlobalPrefix("api/v1");
  await app.init();
  return { app, server: app.getHttpServer() as Server, auth };
}

async function request(
  server: Server,
  path: string,
  init: RequestInit = {},
): Promise<{ status: number; cacheControl: string | null; body: Record<string, unknown> }> {
  const body = typeof init.body === "string" ? Buffer.from(init.body, "utf8") : undefined;
  const headers = new Headers(init.headers);
  if (body !== undefined && !headers.has("content-length")) {
    headers.set("content-length", String(body.length));
  }
  const request = Readable.from(body === undefined ? [] : [body]);
  const socket = {
    destroyed: false,
    encrypted: false,
    remoteAddress: "127.0.0.1",
    remotePort: 32123,
  };
  Object.assign(request, {
    method: init.method ?? "GET",
    url: path,
    headers: Object.fromEntries(headers.entries()),
    httpVersion: "1.1",
    httpVersionMajor: 1,
    httpVersionMinor: 1,
    complete: false,
    aborted: false,
    socket,
    connection: socket,
  });
  const response = new ServerResponse(request as IncomingMessage);
  const chunks: Buffer[] = [];
  const responseWithCapture = response as ServerResponse & {
    bodyChunks?: Buffer[];
    headersSent: boolean;
  };
  responseWithCapture.bodyChunks = chunks;
  Object.defineProperty(responseWithCapture, "headersSent", {
    configurable: true,
    enumerable: true,
    value: false,
    writable: true,
  });
  const responseAny = response as unknown as {
    end: (chunk?: unknown, encoding?: unknown, callback?: () => void) => ServerResponse;
    write: (chunk: unknown, encoding?: unknown, callback?: () => void) => boolean;
  };
  responseAny.write = (chunk: unknown) => {
    if (chunk !== undefined)
      chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk)));
    return true;
  };
  responseAny.end = (chunk?: unknown, _encoding?: unknown, callback?: () => void) => {
    if (chunk !== undefined)
      chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk)));
    responseWithCapture.headersSent = true;
    response.emit("finish");
    callback?.();
    return response;
  };

  const completed = new Promise<void>((resolve, reject) => {
    response.once("finish", resolve);
    response.once("error", reject);
  });
  server.emit("request", request as unknown as IncomingMessage, response);
  await completed;
  const text = Buffer.concat(chunks).toString("utf8");
  return {
    status: response.statusCode,
    cacheControl: response.getHeader("cache-control")?.toString() ?? null,
    body: JSON.parse(text) as Record<string, unknown>,
  };
}

describe("market-data settings HTTP boundary", () => {
  const key = randomBytes(32);
  let app: INestApplication;
  let server: Server;
  let auth: TestApp["auth"];
  let unconfiguredApp: INestApplication;
  let unconfiguredServer: Server;

  beforeAll(async () => {
    const tokenEnvelope = encryptToken("worker-secret", key);
    const configured = await createTestApp(
      {
        provider: "tushare",
        revision: 3,
        tokenEnvelope,
        updatedAt: "2026-09-05T00:00:00.000Z",
      },
      { getKey: () => Buffer.from(key) },
      WORKER_TOKEN,
    );
    app = configured.app;
    server = configured.server;
    auth = configured.auth;

    const unavailable = await createTestApp(
      null,
      {
        getKey: () => {
          throw new Error("missing key");
        },
      },
      WORKER_TOKEN,
    );
    unconfiguredApp = unavailable.app;
    unconfiguredServer = unavailable.server;
  });

  afterAll(async () => {
    await Promise.all([app?.close(), unconfiguredApp?.close()]);
  });

  it("rejects anonymous and non-admin browser reads before exposing settings", async () => {
    await expect(request(server, "/api/v1/market-data/settings")).resolves.toMatchObject({
      status: 401,
    });

    const nonAdmin = await request(server, "/api/v1/market-data/settings", {
      headers: { cookie: `__Host-kunlun_session=${VIEWER_COOKIE}` },
    });
    expect(nonAdmin.status).toBe(403);
    expect(nonAdmin.body).not.toHaveProperty("token");
  });

  it("requires CSRF for browser writes and returns no-store safe fields", async () => {
    const missingCsrf = await request(server, "/api/v1/market-data/settings", {
      method: "POST",
      headers: {
        cookie: `__Host-kunlun_session=${ADMIN_COOKIE}`,
        origin: PUBLIC_ORIGIN,
        "content-type": "application/json",
      },
      body: JSON.stringify({
        schemaVersion: "market-data-settings-update-v1",
        expectedRevision: 3,
        provider: "tushare",
        tokenAction: "KEEP",
      }),
    });
    expect(missingCsrf.status).toBe(403);

    const adminRead = await request(server, "/api/v1/market-data/settings", {
      headers: { cookie: `__Host-kunlun_session=${ADMIN_COOKIE}` },
    });
    expect(adminRead.status).toBe(200);
    expect(adminRead.cacheControl).toBe("no-store");
    expect(adminRead.body).toEqual({
      schemaVersion: "market-data-settings-v1",
      provider: "tushare",
      revision: 3,
      tokenConfigured: true,
      updatedAt: "2026-09-05T00:00:00.000Z",
    });
    expect(adminRead.body).not.toHaveProperty("token");
  });

  it("allows only the exact worker bearer on the internal read route", async () => {
    const worker = await request(server, "/api/v1/internal/market-data/settings", {
      headers: { authorization: `Bearer ${WORKER_TOKEN}` },
    });
    expect(worker.status).toBe(200);
    expect(worker.cacheControl).toBe("no-store");
    expect(worker.body).toEqual({
      schemaVersion: "market-data-worker-settings-v1",
      provider: "tushare",
      revision: 3,
      token: "worker-secret",
    });

    const browserMetadata = await request(server, "/api/v1/internal/market-data/settings", {
      headers: {
        authorization: `Bearer ${WORKER_TOKEN}`,
        origin: PUBLIC_ORIGIN,
      },
    });
    expect(browserMetadata.status).toBe(401);

    const normalRoute = await request(server, "/api/v1/normal", {
      headers: { authorization: `Bearer ${WORKER_TOKEN}` },
    });
    expect(normalRoute.status).toBe(401);
    expect(auth.authenticate).not.toHaveBeenCalledWith(WORKER_TOKEN);
  });

  it("maps missing settings secrets to a generic 503 without fallback", async () => {
    const unavailable = await request(unconfiguredServer, "/api/v1/internal/market-data/settings", {
      headers: { authorization: `Bearer ${WORKER_TOKEN}` },
    });
    expect(unavailable.status).toBe(503);
    expect(unavailable.body).toMatchObject({
      statusCode: 503,
      message: "行情源配置暂时不可用",
    });
    expect(JSON.stringify(unavailable.body)).not.toMatch(/missing key|postgres|secret/i);
  });
});
