import { describe, expect, it } from "vitest";

import { rankingAcceptanceSnapshot } from "./ranking-fixture";
import {
  clampMinimumScore,
  exclusionReasonLabel,
  filterRankingRows,
  formatShanghaiTime,
  rankingContextNotice,
} from "./ranking-terminal-model";

describe("ranking terminal model", () => {
  it("filters the server-shaped snapshot without recalculating global ranks", () => {
    const rows = filterRankingRows(rankingAcceptanceSnapshot, {
      query: "平安银行",
      sector: "银行",
      minimumScoreBps: 600,
      includeExcluded: false,
    });

    expect(rows).toHaveLength(1);
    expect(rows[0]?.instrumentId).toBe("000001.SZ");
    expect(rows[0]?.rank).toBe(4);
  });

  it("keeps excluded explanations opt-in", () => {
    expect(
      filterRankingRows(rankingAcceptanceSnapshot, {
        query: "",
        sector: null,
        minimumScoreBps: null,
        includeExcluded: false,
      }),
    ).toHaveLength(4);
    expect(
      filterRankingRows(rankingAcceptanceSnapshot, {
        query: "",
        sector: null,
        minimumScoreBps: null,
        includeExcluded: true,
      }),
    ).toHaveLength(5);
  });

  it("parses score boundaries without propagating NaN", () => {
    expect(clampMinimumScore("")).toBeNull();
    expect(clampMinimumScore("not-a-number")).toBeNull();
    expect(clampMinimumScore("-1")).toBe(0);
    expect(clampMinimumScore("120")).toBe(10_000);
    expect(clampMinimumScore("63.25")).toBe(6_325);
  });

  it("renders evidence time in Asia/Shanghai", () => {
    expect(formatShanghaiTime("2026-08-26T07:00:00Z")).toContain("15:00:00");
  });

  it("explicitly rejects global URL context for the fixed fixture", () => {
    expect(
      rankingContextNotice(new URLSearchParams("asOf=2026-08-24T07:00:00Z&instrument=600519.SH")),
    ).toContain("固定验收快照未应用 URL 上下文：asOf、instrument");
    expect(rankingContextNotice(new URLSearchParams())).toBeNull();
  });

  it("translates required-feature exclusions with the configured label", () => {
    expect(
      exclusionReasonLabel(
        "MISSING_REQUIRED_FEATURE:quality",
        rankingAcceptanceSnapshot.spec.features,
      ),
    ).toBe("必需特征缺失：质量因子");
  });
});
