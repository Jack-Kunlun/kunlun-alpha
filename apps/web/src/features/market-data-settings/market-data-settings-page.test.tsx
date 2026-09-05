import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { MarketDataSettingsResponse } from "@kunlun/shared-types";
import { buildMarketDataSettingsUpdate } from "./market-data-settings-client";
import { MarketDataSettingsPage } from "./market-data-settings-page";
import {
  draftFromMarketDataSettings,
  shouldSyncMarketDataSettingsDraft,
} from "./market-data-settings-page";
import { useMarketDataSettings } from "./use-market-data-settings";

vi.mock("./use-market-data-settings", () => ({
  useMarketDataSettings: vi.fn(),
}));

const mockedUseMarketDataSettings = vi.mocked(useMarketDataSettings);

const base = {
  schemaVersion: "market-data-settings-v1" as const,
  provider: "akshare" as const,
  revision: 0,
  tokenConfigured: false,
  updatedAt: null,
};

function mockResult(
  status: "loading" | "empty" | "error" | "forbidden" | "unavailable" | "success",
  data: MarketDataSettingsResponse | null =
    status === "empty" || status === "success" ? base : null,
) {
  mockedUseMarketDataSettings.mockReturnValue({
    query: { status, data, error: null },
    saving: false,
    saveError: null,
    saved: false,
    refresh: vi.fn(),
    save: vi.fn(),
    clearSaveError: vi.fn(),
  });
}

describe("MarketDataSettingsPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders loading, empty revision zero, forbidden and unavailable states", () => {
    mockResult("loading");
    expect(renderToStaticMarkup(<MarketDataSettingsPage />)).toContain("正在加载");

    mockResult("empty");
    const empty = renderToStaticMarkup(<MarketDataSettingsPage />);
    expect(empty).toContain("revision 0");
    expect(empty).toContain("尚未保存");

    mockResult("forbidden");
    expect(renderToStaticMarkup(<MarketDataSettingsPage />)).toContain("无权访问");

    mockResult("unavailable");
    expect(renderToStaticMarkup(<MarketDataSettingsPage />)).toContain("暂时不可用");
  });

  it("renders controlled retry/error states without raw backend text", () => {
    mockedUseMarketDataSettings.mockReturnValue({
      query: { status: "error", data: null, error: new Error("secret-token") },
      saving: false,
      saveError: "配置服务暂时不可用，请稍后重试",
      saved: false,
      refresh: vi.fn(),
      save: vi.fn(),
      clearSaveError: vi.fn(),
    });
    const html = renderToStaticMarkup(<MarketDataSettingsPage />);
    expect(html).toContain("加载行情源配置失败");
    expect(html).toContain("重试");
    expect(html).not.toContain("secret-token");
  });

  it("keeps the token input empty and exposes labeled, keyboard-safe controls", () => {
    mockResult("success", { ...base, revision: 2, tokenConfigured: true });
    const html = renderToStaticMarkup(<MarketDataSettingsPage />);
    expect(html).toContain('for="market-data-provider"');
    expect(html).toContain('for="market-data-token"');
    expect(html).toContain('for="market-data-token-keep"');
    expect(html).toContain('for="market-data-token-replace"');
    expect(html).toContain('for="market-data-token-clear"');
    expect(html).toContain('type="password"');
    expect(html).toContain('value=""');
    expect(html).toContain("实例级");
    expect(html).toContain("下一轮读取");
    expect(html).toContain("不确认运行生效");
    expect(html).not.toContain("tokenConfigured");
  });

  it("syncs an untouched refresh to the rendered provider and submitted revision", () => {
    const refreshed = {
      ...base,
      provider: "tushare" as const,
      revision: 7,
      tokenConfigured: true,
      updatedAt: "2026-09-05T01:02:03.000Z",
    };
    expect(
      shouldSyncMarketDataSettingsDraft({
        draftTouched: false,
        force: false,
        lastSyncedRevision: 0,
        nextRevision: refreshed.revision,
      }),
    ).toBe(true);
    const draft = draftFromMarketDataSettings(refreshed);
    expect(draft).toEqual({
      provider: "tushare",
      tokenAction: "KEEP",
      token: "",
      clearConfirmed: false,
    });
    expect(
      buildMarketDataSettingsUpdate({
        expectedRevision: refreshed.revision,
        provider: draft.provider,
        tokenAction: draft.tokenAction,
        token: draft.token,
      }),
    ).toMatchObject({ expectedRevision: 7, provider: "tushare", tokenAction: "KEEP" });

    mockResult("success", refreshed);
    expect(renderToStaticMarkup(<MarketDataSettingsPage />)).toContain("Tushare");
  });

  it("does not synchronize an actively edited draft from a passive response", () => {
    expect(
      shouldSyncMarketDataSettingsDraft({
        draftTouched: true,
        force: false,
        lastSyncedRevision: 0,
        nextRevision: 7,
      }),
    ).toBe(false);
  });
});
