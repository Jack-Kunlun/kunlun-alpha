import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AlertsPage, evaluationRunStatus } from "./alerts-page";
import { CreateRuleForm } from "./create-rule-drawer";
import { Dialog } from "../../components/ui/dialog";
import { useWatchlistAlerts } from "./use-watchlist-alerts";

vi.mock("./use-watchlist-alerts", () => ({
  requestId: () => "test-request-id",
  useWatchlistAlerts: vi.fn(),
}));

const mockedUseWatchlistAlerts = vi.mocked(useWatchlistAlerts);

describe("AlertsPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("keeps the rule list separate from creation until the user opens the drawer", () => {
    mockedUseWatchlistAlerts.mockReturnValue(model("empty"));

    const html = renderToStaticMarkup(<AlertsPage />);

    expect(html).toContain("自选规则与预警");
    expect(html).toContain("还没有预警规则");
    expect(html).toContain("新建规则");
    expect(html).not.toContain("<form");
    expect(html).not.toContain("规则名称");
    expect(html).not.toContain("从左侧创建");
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

  it("keeps legacy rule management in the list and auto-evaluated fields in the drawer form", () => {
    mockedUseWatchlistAlerts.mockReturnValue(model("ready"));

    const html = renderToStaticMarkup(<AlertsPage />);
    const formHtml = renderToStaticMarkup(
      <Dialog open>
        <CreateRuleForm disabled={false} onCreate={vi.fn()} onCancel={vi.fn()} />
      </Dialog>,
    );

    expect(formHtml).toMatch(/<option[^>]+value="LAST_PRICE"[^>]*>最新价<\/option>/);
    expect(formHtml).toMatch(/<option[^>]+value="CHANGE_BPS"[^>]*>涨跌幅 BPS<\/option>/);
    expect(formHtml).not.toMatch(/<option[^>]+value="EMOTION_SCORE_BPS"/);
    expect(formHtml).not.toMatch(/<option[^>]+value="FEATURE_VALUE"/);
    expect(formHtml).toContain("取消");
    expect(formHtml).toContain("保存规则");
    expect(html).not.toContain("<form");
    expect(html).toContain("本版本不自动评估");
    expect(html.match(/阈值预览/g)).toHaveLength(1);
    expect(html.match(/>编辑</g)).toHaveLength(2);
  });

  it("labels partial evaluation failures as failures while retaining the completion state", () => {
    expect(evaluationRunStatus(evaluationRun({ failed: 1 }))).toEqual({
      title: "行情评估存在失败",
      role: "alert",
      tone: "failure",
    });
    expect(evaluationRunStatus(evaluationRun({ failed: 0 }))).toEqual({
      title: "最新行情评估完成",
      role: "status",
      tone: "success",
    });
  });
});

function evaluationRun(
  values: Partial<{
    evaluated: number;
    skippedNoData: number;
    skippedUnsupported: number;
    failed: number;
  }>,
) {
  return {
    schemaVersion: "watchlist-alert-evaluation-run-v1" as const,
    generatedAt: "2026-08-26T00:00:00.000Z",
    rulesScanned: 2,
    evaluated: values.evaluated ?? 1,
    skippedNoData: values.skippedNoData ?? 0,
    skippedUnsupported: values.skippedUnsupported ?? 0,
    failed: values.failed ?? 0,
    dataMeaning: "RESEARCH_ALERT_EVALUATION_NO_ORDER_PATH" as const,
  };
}

function model(state: "empty" | "forbidden" | "error" | "ready") {
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
        : state === "ready"
          ? {
              schemaVersion: "watchlist-alerts-workspace-v1" as const,
              ruleLanguage: "BOUNDED_COMPARISON_V1" as const,
              generatedAt: "2026-08-26T00:00:00.000Z",
              rules: [rule("LAST_PRICE", null), rule("FEATURE_VALUE", "momentum_20d")],
              history: [],
              supportedFields: ["LAST_PRICE", "CHANGE_BPS"] as const,
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
    updateRule: vi.fn().mockResolvedValue(undefined),
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

function rule(
  field: "LAST_PRICE" | "FEATURE_VALUE",
  featureName: string | null,
): NonNullable<ReturnType<typeof useWatchlistAlerts>["workspace"]>["rules"][number] {
  const ruleId = field === "LAST_PRICE" ? "a".repeat(64) : "b".repeat(64);
  return {
    schemaVersion: "watchlist-alert-rule-v1",
    ruleId,
    revisionId: field === "LAST_PRICE" ? "c".repeat(64) : "d".repeat(64),
    revision: 1,
    name: field === "LAST_PRICE" ? "价格提醒" : "旧特征提醒",
    enabled: true,
    instrumentIds: ["600519.SH"],
    condition: { field, operator: "GTE", threshold: "1500.00", featureName },
    quietPeriod: null,
    throttleSeconds: 300,
    notificationChannel: "IN_APP",
    createdAt: "2026-08-26T00:00:00.000Z",
    availableAt: "2026-08-26T00:00:00.000Z",
    previousRevisionId: null,
  };
}
