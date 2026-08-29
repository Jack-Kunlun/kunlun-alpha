import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AlertsPage } from "./alerts-page";
import { useWatchlistAlerts } from "./use-watchlist-alerts";

vi.mock("./use-watchlist-alerts", () => ({
  requestId: () => "test-request-id",
  useWatchlistAlerts: vi.fn(),
}));

const mockedUseWatchlistAlerts = vi.mocked(useWatchlistAlerts);

describe("AlertsPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders an explicit empty state and bounded rule composer", () => {
    mockedUseWatchlistAlerts.mockReturnValue(model("empty"));

    const html = renderToStaticMarkup(<AlertsPage />);

    expect(html).toContain("自选规则与预警");
    expect(html).toContain("还没有预警规则");
    expect(html).toContain("指标");
    expect(html).toContain("立即评估最新行情");
    expect(html).not.toMatch(/P6|Phase/);
  });

  it("renders forbidden and failure recovery states", () => {
    mockedUseWatchlistAlerts.mockReturnValue(model("forbidden"));
    expect(renderToStaticMarkup(<AlertsPage />)).toContain("当前终端未配置预警所有者");

    mockedUseWatchlistAlerts.mockReturnValue(model("error"));
    const errorHtml = renderToStaticMarkup(<AlertsPage />);
    expect(errorHtml).toContain("预警工作区暂不可用");
    expect(errorHtml).toContain("重新加载");
  });
});

function model(state: "empty" | "forbidden" | "error") {
  return {
    workspace:
      state === "empty"
        ? {
            schemaVersion: "watchlist-alerts-workspace-v1" as const,
            ruleLanguage: "BOUNDED_COMPARISON_V1" as const,
            generatedAt: "2026-08-26T00:00:00.000Z",
            rules: [],
            history: [],
            supportedFields: ["LAST_PRICE"] as const,
            supportedOperators: ["GTE"] as const,
            dataMeaning: "RESEARCH_ALERTS_ONLY_NO_ORDER_PATH" as const,
          }
        : null,
    state,
    error: state === "error" ? "server unavailable" : null,
    submitting: false,
    refresh: vi.fn().mockResolvedValue(undefined),
    createRule: vi.fn().mockResolvedValue(undefined),
    toggleRule: vi.fn().mockResolvedValue(undefined),
    preview: vi.fn().mockResolvedValue({ outcome: "TRIGGERED", detail: "preview" }),
    evaluateLatest: vi.fn().mockResolvedValue({
      schemaVersion: "watchlist-alert-evaluation-run-v1",
      generatedAt: "2026-08-26T00:00:00.000Z",
      rulesScanned: 0,
      evaluated: 0,
      skippedUnsupported: 0,
      skippedNoData: 0,
      failed: 0,
      dataMeaning: "RESEARCH_ALERT_EVALUATION_NO_ORDER_PATH",
    }),
  } as ReturnType<typeof useWatchlistAlerts>;
}
