import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { rankingAcceptanceSnapshot } from "./ranking-fixture";
import {
  ContributionEvidence,
  RankingEvidenceDialog,
  RankingTerminalView,
} from "./ranking-terminal-page";
import type { RankingSnapshot } from "./types";

describe("RankingTerminalView", () => {
  it("labels the acceptance fixture and avoids return guarantees", () => {
    const html = renderToStaticMarkup(
      <RankingTerminalView result={{ state: "success", snapshot: rankingAcceptanceSnapshot }} />,
    );

    expect(html).toContain("脱敏验收快照");
    expect(html).toContain("本节点尚未接入实时 Ranking 读取端");
    expect(html).toContain("研究排序，不构成收益保证");
    expect(html).toContain("快照时点尚不可用");
    expect(html).toContain("查看贡献 · 缺失 1");
    expect(html).not.toContain("<main");
  });

  it.each([
    ["loading", "正在加载 Intelligence Ranking"],
    ["forbidden", "无权查看股票智能排序"],
    ["error", "排名快照加载失败"],
  ] as const)("renders the %s state", (state, expected) => {
    const result =
      state === "loading"
        ? ({ state } as const)
        : ({ state, message: "acceptance-state-message" } as const);
    const html = renderToStaticMarkup(<RankingTerminalView result={result} />);
    expect(html).toContain(expected);
  });

  it("renders a deliberate empty-filter state", () => {
    const html = renderToStaticMarkup(
      <RankingTerminalView
        result={{ state: "success", snapshot: rankingAcceptanceSnapshot }}
        initialFilters={{ query: "不存在的证券" }}
      />,
    );

    expect(html).toContain("当前筛选没有匹配记录");
  });

  it("warns when the fixed fixture does not apply route context", () => {
    const html = renderToStaticMarkup(
      <RankingTerminalView
        result={{ state: "success", snapshot: rankingAcceptanceSnapshot }}
        contextNotice="固定验收快照未应用 URL 上下文：asOf、instrument。"
      />,
    );

    expect(html).toContain("URL 上下文未应用");
    expect(html).toContain("固定验收快照未应用 URL 上下文");
  });

  it("explains RENORMALIZE and ZERO with configured and effective weights", () => {
    const renormalizedItem = rankingAcceptanceSnapshot.rows
      .find((row) => row.instrumentId === "300750.SZ")
      ?.contributions.find((item) => item.featureKey === "quality");
    const zeroItem = rankingAcceptanceSnapshot.rows
      .find((row) => row.instrumentId === "688981.SH")
      ?.contributions.find((item) => item.featureKey === "risk");
    const qualitySpec = rankingAcceptanceSnapshot.spec.features.find(
      (feature) => feature.key === "quality",
    );
    const riskSpec = rankingAcceptanceSnapshot.spec.features.find(
      (feature) => feature.key === "risk",
    );
    if (!renormalizedItem || !zeroItem || !qualitySpec || !riskSpec) {
      throw new Error("acceptance fixture must contain missing-policy examples");
    }

    const renormalizedHtml = renderToStaticMarkup(
      <ContributionEvidence item={renormalizedItem} feature={qualitySpec} />,
    );
    const zeroHtml = renderToStaticMarkup(
      <ContributionEvidence item={zeroItem} feature={riskSpec} />,
    );

    expect(renormalizedHtml).toContain("缺失权重重归一化");
    expect(renormalizedHtml).toContain("配置权重");
    expect(renormalizedHtml).toContain("20.0%");
    expect(renormalizedHtml).toContain("有效权重");
    expect(zeroHtml).toContain("缺失计零分");
    expect(zeroHtml).toContain("15.0%");
  });

  it("wires included RENORMALIZE and ZERO examples into the ranking page", () => {
    const renormalizedRow = rankingAcceptanceSnapshot.rows.find(
      (row) => row.instrumentId === "300750.SZ",
    );
    const zeroRow = rankingAcceptanceSnapshot.rows.find((row) => row.instrumentId === "601318.SH");
    if (!renormalizedRow || !zeroRow) {
      throw new Error("acceptance fixture must contain included missing-policy rows");
    }

    const pageHtml = renderToStaticMarkup(
      <RankingTerminalView result={{ state: "success", snapshot: rankingAcceptanceSnapshot }} />,
    );
    const renormalizedHtml = renderToStaticMarkup(
      <RankingEvidenceDialog row={renormalizedRow} spec={rankingAcceptanceSnapshot.spec} />,
    );
    const zeroHtml = renderToStaticMarkup(
      <RankingEvidenceDialog row={zeroRow} spec={rankingAcceptanceSnapshot.spec} />,
    );

    expect(pageHtml).toContain("缺失权重重归一化");
    expect(pageHtml).toContain("缺失计零分");
    expect(renormalizedHtml).toContain("趋势强度：配置");
    expect(renormalizedHtml).toContain("40.0%");
    expect(renormalizedHtml).toContain("50.0%");
    expect(zeroHtml).toContain("配置 15.0%");
    expect(zeroHtml).toContain("有效 15.0%");
    expect(zeroHtml).toContain("贡献 0.00");
  });

  it("renders required-feature exclusions with a human label", () => {
    const sourceRow = rankingAcceptanceSnapshot.rows[0];
    if (!sourceRow) throw new Error("acceptance fixture must contain a row");
    const snapshot: RankingSnapshot = {
      ...rankingAcceptanceSnapshot,
      rows: [
        {
          ...sourceRow,
          status: "EXCLUDED",
          rank: null,
          scoreBps: null,
          exclusionReasons: ["MISSING_REQUIRED_FEATURE:quality"],
        },
      ],
    };

    const html = renderToStaticMarkup(
      <RankingTerminalView
        result={{ state: "success", snapshot }}
        initialFilters={{ includeExcluded: true }}
      />,
    );

    expect(html).toContain("必需特征缺失：质量因子");
    expect(html).not.toContain("MISSING_REQUIRED_FEATURE:quality");
  });
});
