import { randomBytes } from "node:crypto";
import {
  BadRequestException,
  ConflictException,
  ForbiddenException,
  ServiceUnavailableException,
} from "@nestjs/common";
import { describe, expect, it, vi } from "vitest";
import { MarketDataSettingsConflictError } from "./market-data-settings.repository";
import { MarketDataSettingsService } from "./market-data-settings.service";
import type {
  MarketDataSettingsRepository,
  PersistedMarketDataSettings,
} from "./market-data-settings.types";

const ADMIN_ID = "9b596d16-8aae-4a10-8aa7-88c8c9f7458e";
const ADMIN_ROLES = ["platform_admin"] as const;
const UPDATE_VERSION = "market-data-settings-update-v1" as const;

function request(
  provider: "akshare" | "tushare",
  tokenAction: "KEEP" | "REPLACE" | "CLEAR",
  expectedRevision = 0,
  token?: string,
) {
  return {
    schemaVersion: UPDATE_VERSION,
    expectedRevision,
    provider,
    tokenAction,
    ...(token === undefined ? {} : { token }),
  };
}

function repository(
  initial: PersistedMarketDataSettings | null = null,
): MarketDataSettingsRepository {
  const state = { current: initial };
  return {
    get: vi.fn(async () => state.current),
    compareAndSet: vi.fn(async (input) => {
      if ((state.current?.revision ?? 0) !== input.expectedRevision) {
        throw new MarketDataSettingsConflictError();
      }
      state.current = {
        provider: input.provider,
        revision: input.expectedRevision + 1,
        tokenEnvelope: input.tokenEnvelope,
        updatedAt: input.updatedAt,
      };
      return state.current;
    }),
  };
}

function keyProvider(key = randomBytes(32)) {
  return { getKey: vi.fn(() => Buffer.from(key)) };
}

describe("MarketDataSettingsService", () => {
  it("checks the trusted administrator before repository or key access", async () => {
    const repo = repository();
    const key = keyProvider();
    const service = new MarketDataSettingsService(repo, key);

    await expect(service.getBrowserSettings("not-an-admin", [])).rejects.toThrow(
      ForbiddenException,
    );
    expect(repo.get).not.toHaveBeenCalled();
    expect(key.getKey).not.toHaveBeenCalled();
  });

  it("returns a safe default and never exposes an encrypted token", async () => {
    const repo = repository();
    const service = new MarketDataSettingsService(repo, keyProvider());

    await expect(service.getBrowserSettings(ADMIN_ID, ADMIN_ROLES)).resolves.toEqual({
      schemaVersion: "market-data-settings-v1",
      provider: "akshare",
      revision: 0,
      tokenConfigured: false,
      updatedAt: null,
    });
  });

  it("stores a Tushare replacement and only decrypts for the worker response", async () => {
    const repo = repository();
    const service = new MarketDataSettingsService(
      repo,
      keyProvider(),
      () => new Date("2026-09-05T00:00:00.000Z"),
    );

    const browserResponse = await service.updateBrowserSettings(
      ADMIN_ID,
      ADMIN_ROLES,
      request("tushare", "REPLACE", 0, "secret-123"),
    );
    expect(browserResponse).toEqual({
      schemaVersion: "market-data-settings-v1",
      provider: "tushare",
      revision: 1,
      tokenConfigured: true,
      updatedAt: "2026-09-05T00:00:00.000Z",
    });
    expect(browserResponse).not.toHaveProperty("token");
    await expect(service.getWorkerSettings()).resolves.toEqual({
      schemaVersion: "market-data-worker-settings-v1",
      provider: "tushare",
      revision: 1,
      token: "secret-123",
    });
  });

  it("never sends an AKShare token to the worker and rejects Tushare clear", async () => {
    const repo = repository();
    const service = new MarketDataSettingsService(repo, keyProvider());
    await service.updateBrowserSettings(
      ADMIN_ID,
      ADMIN_ROLES,
      request("akshare", "REPLACE", 0, "saved"),
    );
    await expect(service.getWorkerSettings()).resolves.toMatchObject({
      provider: "akshare",
      token: null,
    });
    await expect(
      service.updateBrowserSettings(ADMIN_ID, ADMIN_ROLES, request("tushare", "CLEAR", 1)),
    ).rejects.toThrow(BadRequestException);
  });

  it("requires the master key for every update action and maps CAS races to 409", async () => {
    const repo = repository();
    const key = {
      getKey: vi.fn(() => {
        throw new Error("missing key");
      }),
    };
    const service = new MarketDataSettingsService(repo, key);
    await expect(
      service.updateBrowserSettings(ADMIN_ID, ADMIN_ROLES, request("akshare", "KEEP")),
    ).rejects.toThrow(ServiceUnavailableException);
    expect(repo.get).not.toHaveBeenCalled();

    const conflictRepo = repository();
    conflictRepo.compareAndSet = vi.fn(async () => {
      throw new MarketDataSettingsConflictError();
    });
    const conflictService = new MarketDataSettingsService(conflictRepo, keyProvider());
    await expect(
      conflictService.updateBrowserSettings(ADMIN_ID, ADMIN_ROLES, request("akshare", "CLEAR")),
    ).rejects.toThrow(ConflictException);
  });
});
