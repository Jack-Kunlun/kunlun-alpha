import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import type { WatchlistAlertsWorkspace, WatchlistAlertHistory } from "@kunlun/shared-types";
import { readAlertHistory, selectAlertHistory, type AlertHistoryFilters } from "./alert-history";
import { AlertHistoryCard } from "./alert-history-card";
import { AlertHistoryCurrentDailyLink, AlertHistoryDetailFields } from "./alert-history-detail";

function row(index = 1): WatchlistAlertHistory {
  return {
    schemaVersion: "watchlist-alert-history-v1",
    historyId: index.toString(16).padStart(64, "0"),
    ruleId: "a".repeat(64),
    revisionId: "b".repeat(64),
    eventId: `bar:${index}`,
    instrumentId: "000001.SZ",
    eventTime: "2026-10-23T07:00:00.000000Z",
    availableTime: "2026-10-26T01:00:00.123456789Z",
    createdAt: "2026-10-26T02:00:00Z",
    outcome: "CONDITION_NOT_MET",
    observedValue: "-123456789123456789.12345678",
    notificationId: null,
    notificationStatus: "NONE",
    detail: "Isolated evaluation evidence",
  };
}
function workspace(rows = [row()]): WatchlistAlertsWorkspace {
  return {
    schemaVersion: "watchlist-alerts-workspace-v1",
    ruleLanguage: "BOUNDED_COMPARISON_V1",
    generatedAt: "2026-10-26T03:00:00.123456789Z",
    rules: [],
    history: rows,
    supportedFields: ["LAST_PRICE"],
    supportedOperators: ["GTE"],
    dataMeaning: "RESEARCH_ALERTS_ONLY_NO_ORDER_PATH",
  };
}
const all: AlertHistoryFilters = { query: "", outcome: "ALL", delivery: "ALL" };

describe("recent evaluation history browsing", () => {
  it("preserves exact observations, three distinct event times and IDs without using current rule metadata", () => {
    const data = workspace();
    data.history[0]!.detail = '<img src=x onerror="alert(1)">';
    const before = JSON.stringify(data);
    const model = readAlertHistory(data);
    expect(model.rows[0]).toEqual(data.history[0]);
    const html = renderToStaticMarkup(
      <AlertHistoryDetailFields row={model.rows[0]!} generatedAt={model.generatedAt} />,
    );
    for (const value of [
      data.history[0]!.observedValue!,
      data.history[0]!.eventTime,
      data.history[0]!.availableTime,
      data.history[0]!.createdAt,
      model.generatedAt,
      data.history[0]!.revisionId,
    ])
      expect(html).toContain(value);
    expect(html).toContain("&lt;img");
    expect(html).not.toContain("<img");
    expect(html).toContain("记录写入时间");
    expect(JSON.stringify(data)).toBe(before);
  });
  it("sorts by exact data availability then descending history ID, without mutating server rows", () => {
    const data = workspace([row(1), row(2), row(3)]);
    data.history[0]!.availableTime = "2026-10-26T09:00:00.123456788+08:00";
    const model = readAlertHistory(data);
    expect(model.rows.map((x) => x.historyId)).toEqual([
      row(3).historyId,
      row(2).historyId,
      row(1).historyId,
    ]);
    expect(data.history[0]!.historyId).toBe(row(1).historyId);
  });
  it("combines code or rule search, outcome and delivery and pages only this recent window", () => {
    const rows = Array.from({ length: 25 }, (_, i) => row(i));
    rows[24] = {
      ...row(24),
      instrumentId: "600519.SH",
      ruleId: "c".repeat(64),
      outcome: "TRIGGERED",
      notificationStatus: "FAILED",
      notificationId: "d".repeat(64),
    };
    const model = readAlertHistory(workspace(rows));
    expect(selectAlertHistory(model.rows, all, 1).rows).toHaveLength(20);
    expect(selectAlertHistory(model.rows, all, 2)).toMatchObject({
      count: 25,
      pageCount: 2,
      page: 2,
    });
    expect(selectAlertHistory(model.rows, all, 2).rows).toHaveLength(5);
    const filters: AlertHistoryFilters = {
      query: " 600519.sh ",
      outcome: "TRIGGERED",
      delivery: "FAILED",
    };
    expect(selectAlertHistory(model.rows, filters, 99)).toMatchObject({
      count: 1,
      page: 1,
      pageCount: 1,
    });
    expect(selectAlertHistory(model.rows, { ...filters, query: "CCCC" }, 1).count).toBe(1);
    expect(selectAlertHistory(model.rows, { ...filters, delivery: "DELIVERED" }, 1)).toMatchObject({
      rows: [],
      count: 0,
      page: 1,
      pageCount: 1,
    });
    expect(selectAlertHistory(model.rows, all, NaN).page).toBe(1);
    expect(model.rows).toHaveLength(25);
  });
  it("retains null observations and all five outcomes without inventing a notification", () => {
    for (const outcome of [
      "CONDITION_NOT_MET",
      "THROTTLED",
      "QUIET_PERIOD",
      "RULE_DISABLED",
    ] as const) {
      const result = readAlertHistory(workspace([{ ...row(), outcome, observedValue: null }]));
      expect(result.rows[0]).toMatchObject({
        outcome,
        observedValue: null,
        notificationId: null,
        notificationStatus: "NONE",
      });
    }
    for (const notificationStatus of ["PENDING", "DELIVERED", "FAILED"] as const) {
      expect(
        readAlertHistory(
          workspace([
            { ...row(), outcome: "TRIGGERED", notificationId: "d".repeat(64), notificationStatus },
          ]),
        ).rows[0]?.notificationStatus,
      ).toBe(notificationStatus);
    }
  });
  it("links canonical histories to current daily data with no inherited historical or security filters", () => {
    for (const instrumentId of ["000001.SZ", "600519.SH", "920000.BJ"]) {
      const html = renderToStaticMarkup(
        <MemoryRouter
          initialEntries={["/watchlists?asOf=2026-01-01T00%3A00%3A00Z&instrument=600000.SH"]}
        >
          <AlertHistoryCurrentDailyLink instrumentId={instrumentId} />
        </MemoryRouter>,
      );
      expect(html).toContain(`href="/instruments/${instrumentId}"`);
      expect(html).not.toContain("asOf=");
      expect(html).toContain("当前已入库日线");
    }
    for (const instrumentId of ["600519.sh", "HK:00700", "../600519.SH", "600519.SH?asOf=now"]) {
      expect(
        renderToStaticMarkup(
          <MemoryRouter>
            <AlertHistoryCurrentDailyLink instrumentId={instrumentId} />
          </MemoryRouter>,
        ),
      ).toBe("");
    }
  });
  it("shows honest window counts, Chinese statuses, empty state and separate detail triggers", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <AlertHistoryCard workspace={workspace()} />
      </MemoryRouter>,
    );
    expect(html).toContain("最近记录，最多 200 条");
    expect(html).toContain("本次读取 1 条，匹配 1 条");
    expect(html).toContain("查看详情");
    expect(html).toContain("无通知");
    expect(html.replace(/<[^>]*>/g, "")).not.toContain("CONDITION_NOT_MET");
    const empty = renderToStaticMarkup(<AlertHistoryCard workspace={workspace([])} />);
    expect(empty).toContain("尚无评估历史");
    expect(empty).not.toContain("查看详情");
  });
  it.each([
    ["duplicate", (v: WatchlistAlertsWorkspace) => v.history.push({ ...v.history[0]! })],
    [
      "more than 200",
      (v: WatchlistAlertsWorkspace) => {
        v.history = Array.from({ length: 201 }, (_, i) => row(i));
      },
    ],
    [
      "future record by 1ns",
      (v: WatchlistAlertsWorkspace) => {
        v.history[0]!.createdAt = "2026-10-26T03:00:00.123456790Z";
      },
    ],
    [
      "availability after creation",
      (v: WatchlistAlertsWorkspace) => {
        v.history[0]!.availableTime = "2026-10-26T02:00:00.000000001Z";
      },
    ],
    [
      "event after availability",
      (v: WatchlistAlertsWorkspace) => {
        v.history[0]!.eventTime = "2026-10-26T01:00:00.123456790Z";
      },
    ],
    [
      "impossible date",
      (v: WatchlistAlertsWorkspace) => {
        v.history[0]!.eventTime = "2026-02-30T00:00:00Z";
      },
    ],
    [
      "excessive timestamp precision",
      (v: WatchlistAlertsWorkspace) => {
        v.history[0]!.availableTime = "2026-10-26T01:00:00.1234567890Z";
      },
    ],
    [
      "invalid observation",
      (v: WatchlistAlertsWorkspace) => {
        v.history[0]!.observedValue = "NaN";
      },
    ],
    [
      "observation beyond contract scale",
      (v: WatchlistAlertsWorkspace) => {
        v.history[0]!.observedValue = "1.123456789";
      },
    ],
    [
      "overlong explanation",
      (v: WatchlistAlertsWorkspace) => {
        v.history[0]!.detail = "x".repeat(241);
      },
    ],
    [
      "overlong event ID",
      (v: WatchlistAlertsWorkspace) => {
        v.history[0]!.eventId = "x".repeat(129);
      },
    ],
    [
      "unsupported outcome",
      (v: WatchlistAlertsWorkspace) => {
        Object.assign(v.history[0]!, { outcome: "UNKNOWN" });
      },
    ],
    [
      "bad code",
      (v: WatchlistAlertsWorkspace) => {
        v.history[0]!.instrumentId = "600519.sh";
      },
    ],
    [
      "notification on non-trigger",
      (v: WatchlistAlertsWorkspace) => {
        v.history[0]!.notificationId = "d".repeat(64);
      },
    ],
    [
      "missing trigger notification",
      (v: WatchlistAlertsWorkspace) => {
        v.history[0]!.outcome = "TRIGGERED";
      },
    ],
    [
      "delivery without notification",
      (v: WatchlistAlertsWorkspace) => {
        v.history[0]!.notificationStatus = "DELIVERED";
      },
    ],
    [
      "wrong meaning",
      (v: WatchlistAlertsWorkspace) => {
        Object.assign(v, { dataMeaning: "LIVE_ORDER" });
      },
    ],
  ] as const)("rejects %s as a whole instead of dropping rows", (_name, mutate) => {
    const data = workspace();
    mutate(data);
    expect(() => readAlertHistory(data)).toThrow();
    const html = renderToStaticMarkup(<AlertHistoryCard workspace={data} />);
    expect(html).toContain('role="alert"');
    expect(html).not.toContain("查看详情");
  });
});
