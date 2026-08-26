import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { LimitPoolTerminalSnapshot } from "@kunlun/shared-types";
import { LimitPoolEvidenceDetails, LimitPoolTerminalView } from "./limit-pool-terminal-page";

const snapshot: LimitPoolTerminalSnapshot = {
  schemaVersion: "limit-pool-terminal-v1",
  mode: "CURRENT",
  requestedAsOf: "2026-08-25T06:42:00.000Z",
  tradingDate: "2026-08-25",
  previousTradingDate: "2026-08-24",
  dataCutoffTime: "2026-08-25T06:40:00.000Z",
  availableTime: "2026-08-25T06:40:01.000Z",
  completeness: "COMPLETE",
  missingReasons: [],
  freshness: { status: "DELAYED", ageSeconds: 120 },
  algorithmVersion: "limit-pool-v2",
  ladderAlgorithmVersion: "board_ladder_v2",
  limitRuleVersion: "cn-limit-rules-v1",
  materializerVersion: "limit-pool-terminal-materializer-v1",
  revision: 2,
  limitUpCount: 1,
  limitDownCount: 0,
  sealedCount: 1,
  totalOpenCount: 0,
  ladder: [
    {
      streakDays: 2,
      count: 1,
      previousDayEligibleCount: 2,
      promotedCount: 1,
      promotionRateBps: 5000,
      algorithmVersion: "board_ladder_v2",
    },
  ],
  entries: [
    {
      instrumentId: "600000.SH",
      name: "浦发银行",
      exchange: "SH",
      listingBoard: "MAIN",
      isSt: false,
      side: "LIMIT_UP",
      state: "SEALED",
      streakDays: 2,
      previousStreakDays: 1,
      openCount: 0,
      priceCny: "11.00",
      previousCloseCny: "10.00",
      firstSealTime: "2026-08-25T01:31:00.000Z",
      lastSealTime: "2026-08-25T01:31:00.000Z",
      eventTime: "2026-08-25T01:31:00.000Z",
      availableTime: "2026-08-25T01:31:01.000Z",
      revision: 1,
      sourceVersion: "vendor-a:v7",
      evidenceId: "limit-600000-1",
      algorithmVersion: "limit-pool-v2",
      ladderAlgorithmVersion: "board_ladder_v2",
      limitRuleVersion: "cn-limit-rules-v1",
      materializerVersion: "limit-pool-terminal-materializer-v1",
      dataMeaning: "LIMIT_POOL_ALGORITHM_OUTPUT",
    },
  ],
  sourceVersions: ["vendor-a:v7"],
  evidenceIds: ["limit-600000-1"],
  dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
};

describe("LimitPoolTerminalPage", () => {
  const props = {
    filters: { search: "", side: "ALL" as const, state: "ALL" as const, minimumStreak: 0 },
    sort: { key: "streakDays" as const, direction: "desc" as const },
    selected: null,
    onFilters: vi.fn(),
    onSort: vi.fn(),
    onSelect: vi.fn(),
  };

  it("labels delayed data and renders auditable evidence semantics", () => {
    const html = renderToStaticMarkup(
      <LimitPoolTerminalView
        result={{ status: "success", data: snapshot, error: null }}
        {...props}
      />,
    );
    expect(html).toContain("延迟 120 秒");
    expect(html).toContain("算法 limit-pool-v2");
    expect(html).toContain("梯队 board_ladder_v2");
    const evidence = renderToStaticMarkup(
      <LimitPoolEvidenceDetails entry={snapshot.entries[0]!} />,
    );
    expect(evidence).toContain("limit-600000-1");
    expect(evidence).toContain("算法输出，不代表可成交价格");
  });

  it("renders empty and forbidden states explicitly", () => {
    const empty = renderToStaticMarkup(
      <LimitPoolTerminalView
        result={{
          status: "success",
          data: { ...snapshot, completeness: "EMPTY", entries: [], ladder: [] },
          error: null,
        }}
        {...props}
      />,
    );
    expect(empty).toContain("该时点没有限涨跌停快照");
    const forbidden = renderToStaticMarkup(
      <LimitPoolTerminalView
        result={{ status: "forbidden", data: null, error: new Error("no") }}
        {...props}
      />,
    );
    expect(forbidden).toContain("无权查看涨跌停终端");
  });

  it("renders partial completeness and every missing reason", () => {
    const html = renderToStaticMarkup(
      <LimitPoolTerminalView
        result={{
          status: "success",
          data: { ...snapshot, completeness: "PARTIAL", missingReasons: ["缺少北交所分钟数据"] },
          error: null,
        }}
        {...props}
      />,
    );
    expect(html).toContain("数据不完整");
    expect(html).toContain("缺少北交所分钟数据");
  });
});
