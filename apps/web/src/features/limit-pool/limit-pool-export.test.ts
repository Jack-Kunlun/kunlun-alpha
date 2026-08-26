import { describe, expect, it } from "vitest";
import { buildLimitPoolCsv } from "./limit-pool-export";
import type { LimitPoolTerminalEntry, LimitPoolTerminalSnapshot } from "@kunlun/shared-types";

const entry: LimitPoolTerminalEntry = {
  instrumentId: "600000.SH",
  name: '浦发,"银行"',
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
};

const snapshot: LimitPoolTerminalSnapshot = {
  schemaVersion: "limit-pool-terminal-v1",
  mode: "HISTORICAL",
  requestedAsOf: "2026-08-25T06:45:00.000Z",
  tradingDate: "2026-08-25",
  previousTradingDate: "2026-08-24",
  dataCutoffTime: "2026-08-25T01:31:00.000Z",
  availableTime: "2026-08-25T01:31:01.000Z",
  completeness: "COMPLETE",
  missingReasons: [],
  freshness: { status: "HISTORICAL", ageSeconds: 19439 },
  algorithmVersion: "limit-pool-v2",
  ladderAlgorithmVersion: "board_ladder_v2",
  limitRuleVersion: "cn-limit-rules-v1",
  materializerVersion: "limit-pool-terminal-materializer-v1",
  revision: 1,
  limitUpCount: 1,
  limitDownCount: 0,
  sealedCount: 1,
  totalOpenCount: 0,
  ladder: [],
  entries: [entry],
  sourceVersions: ["vendor-a:v7"],
  evidenceIds: ["limit-600000-1"],
  dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
};

describe("buildLimitPoolCsv", () => {
  it("exports the visible order with deterministic quoting and semantic versions", () => {
    const csv = buildLimitPoolCsv(snapshot);
    expect(csv.startsWith("\uFEFF")).toBe(true);
    expect(csv).toContain('"浦发,""银行"""');
    expect(csv).toContain(
      '"limit-pool-v2","board_ladder_v2","cn-limit-rules-v1","limit-pool-terminal-materializer-v1"',
    );
    expect(csv).toContain(
      '"2026-08-25T06:45:00.000Z","2026-08-25T01:31:00.000Z","2026-08-25T01:31:01.000Z"',
    );
    expect(csv).toContain('"vendor-a:v7","limit-600000-1","RESEARCH_ONLY_NO_REAL_ORDER_PATH"');
    expect(csv.split("\r\n")).toHaveLength(3);
  });

  it("neutralizes spreadsheet formulas from external text fields", () => {
    const csv = buildLimitPoolCsv(snapshot, [
      { ...entry, name: '=HYPERLINK("https://example.invalid")' },
    ]);
    expect(csv).toContain('"\'=HYPERLINK(""https://example.invalid"")"');
  });
});
