import "reflect-metadata";
import { UnauthorizedException, type ExecutionContext } from "@nestjs/common";
import { Reflector } from "@nestjs/core";
import { describe, expect, it, vi } from "vitest";
import { AuthenticationGuard } from "../auth/auth.guard";
import type { AuthService } from "../auth/auth.service";
import { MarketDataStatusController } from "./market-data-status.controller";

describe("market task status authentication", () => {
  it("requires the existing administrator session for the actual status handler", async () => {
    const auth = { authenticate: vi.fn() } as unknown as AuthService;
    const guard = new AuthenticationGuard(new Reflector(), auth, {
      postgresDsn: "postgresql://local.invalid/kunlun",
      publicOrigin: "http://localhost:5173",
      cookieName: "kunlun_session",
      secureCookie: false,
      idleTimeoutMs: 1,
      absoluteTimeoutMs: 1,
      loginWindowMs: 1,
      usernameAttemptLimit: 1,
      globalAttemptLimit: 1,
    });
    const context = {
      getClass: () => MarketDataStatusController,
      getHandler: () => MarketDataStatusController.prototype.status,
      switchToHttp: () => ({ getRequest: () => ({ method: "GET", headers: {} }) }),
    } as unknown as ExecutionContext;
    await expect(guard.canActivate(context)).rejects.toBeInstanceOf(UnauthorizedException);
    expect(auth.authenticate).not.toHaveBeenCalled();
  });
});
