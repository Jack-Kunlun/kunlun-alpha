import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api-client";
import {
  buildMarketDataSettingsUpdate,
  marketDataSettingsErrorMessage,
  validateMarketDataSettingsResponse,
} from "./market-data-settings-client";

const response = {
  schemaVersion: "market-data-settings-v1" as const,
  provider: "akshare" as const,
  revision: 0,
  tokenConfigured: false,
  updatedAt: null,
};

describe("market data settings client contract", () => {
  it("accepts only the closed, secret-free browser response", () => {
    expect(validateMarketDataSettingsResponse(response)).toEqual(response);
    expect(() => validateMarketDataSettingsResponse({ ...response, token: "secret" })).toThrow(
      "行情源配置响应无效",
    );
    expect(() => validateMarketDataSettingsResponse({ ...response, provider: "unknown" })).toThrow(
      "行情源配置响应无效",
    );
  });

  it("creates KEEP and CLEAR payloads without a token field", () => {
    expect(
      buildMarketDataSettingsUpdate({
        expectedRevision: 3,
        provider: "akshare",
        tokenAction: "KEEP",
        token: "",
      }),
    ).toEqual({
      schemaVersion: "market-data-settings-update-v1",
      expectedRevision: 3,
      provider: "akshare",
      tokenAction: "KEEP",
    });
    expect(
      buildMarketDataSettingsUpdate({
        expectedRevision: 3,
        provider: "akshare",
        tokenAction: "CLEAR",
        token: "",
      }),
    ).toEqual({
      schemaVersion: "market-data-settings-update-v1",
      expectedRevision: 3,
      provider: "akshare",
      tokenAction: "CLEAR",
    });
  });

  it("requires a printable non-space token for REPLACE and rejects secrets in other actions", () => {
    expect(
      buildMarketDataSettingsUpdate({
        expectedRevision: 2,
        provider: "tushare",
        tokenAction: "REPLACE",
        token: "token-123",
      }),
    ).toEqual({
      schemaVersion: "market-data-settings-update-v1",
      expectedRevision: 2,
      provider: "tushare",
      tokenAction: "REPLACE",
      token: "token-123",
    });
    expect(() =>
      buildMarketDataSettingsUpdate({
        expectedRevision: 2,
        provider: "tushare",
        tokenAction: "REPLACE",
        token: " has-space",
      }),
    ).toThrow("token 格式无效");
    expect(() =>
      buildMarketDataSettingsUpdate({
        expectedRevision: 2,
        provider: "akshare",
        tokenAction: "KEEP",
        token: "secret",
      }),
    ).toThrow("KEEP/CLEAR 不接受 token");
  });

  it("maps response statuses to controlled messages without echoing raw errors", () => {
    expect(marketDataSettingsErrorMessage(new ApiError("secret token", 409))).toContain(
      "其他操作更新",
    );
    expect(marketDataSettingsErrorMessage(new ApiError("secret token", 503))).toContain(
      "暂时不可用",
    );
    expect(marketDataSettingsErrorMessage(new Error("secret token"))).not.toContain("secret token");
  });
});
