import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { LimitPoolTerminalEntry } from "@kunlun/shared-types";
import { virtualWindowFor, VirtualizedLimitPoolTable } from "./virtualized-limit-pool-table";

function entries(count: number): LimitPoolTerminalEntry[] {
  return Array.from({ length: count }, (_, index) => ({
    instrumentId: `${String(600000 + index)}.SH`,
    name: `样本${index}`,
    exchange: "SH",
    listingBoard: "MAIN",
    isSt: false,
    side: "LIMIT_UP",
    state: "SEALED",
    streakDays: (index % 5) + 1,
    previousStreakDays: index % 5,
    openCount: index % 3,
    priceCny: "11.00",
    previousCloseCny: "10.00",
    firstSealTime: "2026-08-25T01:31:00.000Z",
    lastSealTime: "2026-08-25T01:31:00.000Z",
    eventTime: "2026-08-25T01:31:00.000Z",
    availableTime: "2026-08-25T01:31:01.000Z",
    revision: 1,
    sourceVersion: "vendor-a:v7",
    evidenceId: `ev-${index}`,
    algorithmVersion: "limit-pool-v2",
    ladderAlgorithmVersion: "board_ladder_v2",
    limitRuleVersion: "cn-limit-rules-v1",
    materializerVersion: "limit-pool-terminal-materializer-v1",
    dataMeaning: "LIMIT_POOL_ALGORITHM_OUTPUT",
  }));
}

describe("VirtualizedLimitPoolTable", () => {
  it("renders a bounded window for a large pool", () => {
    const html = renderToStaticMarkup(
      <VirtualizedLimitPoolTable
        entries={entries(2000)}
        sort={{ key: "streakDays", direction: "desc" }}
        onSort={vi.fn()}
        onSelect={vi.fn()}
      />,
    );
    expect(html).toContain('aria-rowcount="2001"');
    expect(html.match(/data-limit-pool-row="true"/g)?.length).toBeLessThan(40);
  });

  it("exposes accessible sort state and selection controls", () => {
    const html = renderToStaticMarkup(
      <VirtualizedLimitPoolTable
        entries={entries(2)}
        sort={{ key: "streakDays", direction: "desc" }}
        onSort={vi.fn()}
        onSelect={vi.fn()}
      />,
    );
    expect(html).toContain('aria-sort="descending"');
    expect(html).toContain('aria-label="按代码排序"');
    expect(html).toContain('aria-label="查看样本0证据"');
    expect(html).toContain('aria-rowindex="2"');
  });

  it("clamps a stale scroll position after filters shrink the pool", () => {
    expect(virtualWindowFor(1, 80_000)).toEqual({ start: 0, end: 1 });
  });
});
