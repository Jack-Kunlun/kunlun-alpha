import type {
  MissingFeaturePolicy,
  RankingFeatureSpec,
  RankingFilters,
  RankingRow,
  RankingSnapshot,
} from "./types";

const SHANGHAI_TIME_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

export const defaultRankingFilters: RankingFilters = {
  query: "",
  sector: null,
  minimumScoreBps: null,
  includeExcluded: false,
};

export function filterRankingRows(
  snapshot: RankingSnapshot,
  filters: RankingFilters,
): readonly RankingRow[] {
  const query = filters.query.trim().toLocaleLowerCase("zh-CN");
  return snapshot.rows.filter((row) => {
    if (!filters.includeExcluded && row.status === "EXCLUDED") return false;
    if (filters.sector !== null && row.sector !== filters.sector) return false;
    if (
      filters.minimumScoreBps !== null &&
      row.scoreBps !== null &&
      row.scoreBps < filters.minimumScoreBps
    ) {
      return false;
    }
    if (!query) return true;
    return `${row.instrumentId} ${row.instrumentName}`.toLocaleLowerCase("zh-CN").includes(query);
  });
}

export function rankingSectors(snapshot: RankingSnapshot): readonly string[] {
  return [...new Set(snapshot.rows.map((row) => row.sector))].sort((left, right) =>
    left.localeCompare(right, "zh-CN"),
  );
}

export function formatScore(scoreBps: number | null): string {
  return scoreBps === null ? "不参与排名" : (scoreBps / 100).toFixed(2);
}

export function formatPercent(bps: number): string {
  return `${(bps / 100).toFixed(1)}%`;
}

export function formatShanghaiTime(instant: string): string {
  return `${SHANGHAI_TIME_FORMATTER.format(new Date(instant))} CST`;
}

export function clampMinimumScore(input: string): number | null {
  if (input.trim() === "") return null;
  const score = Number(input);
  if (!Number.isFinite(score)) return null;
  return Math.round(Math.min(100, Math.max(0, score)) * 100);
}

export function missingReasonLabel(reason: string): string {
  const labels: Record<string, string> = {
    FEATURE_NOT_PROVIDED: "特征未提供",
    NOT_AVAILABLE_AT_SNAPSHOT: "快照时点尚不可用",
    UPSTREAM_VALUE_MISSING: "上游值缺失",
    COVERAGE_BELOW_MINIMUM: "覆盖率低于 RankingSpec 门槛",
    NO_AVAILABLE_FEATURES: "没有任何快照时点可用特征",
  };
  return labels[reason] ?? reason;
}

export function exclusionReasonLabel(
  reason: string,
  features: readonly RankingFeatureSpec[],
): string {
  const prefix = "MISSING_REQUIRED_FEATURE:";
  if (!reason.startsWith(prefix)) return missingReasonLabel(reason);
  const key = reason.slice(prefix.length);
  const feature = features.find((item) => item.key === key);
  return `必需特征缺失：${feature?.label ?? key}`;
}

export function missingPolicyLabel(policy: MissingFeaturePolicy): string {
  const labels: Record<MissingFeaturePolicy, string> = {
    EXCLUDE: "缺失即排除",
    ZERO: "缺失计零分",
    RENORMALIZE: "缺失权重重归一化",
  };
  return labels[policy];
}

export function rankingContextNotice(searchParams: URLSearchParams): string | null {
  const ignored: string[] = [];
  if (searchParams.get("instrument") !== null) ignored.push("instrument");
  if (ignored.length === 0) return null;
  return `Ranking 快照未应用 URL 上下文：${ignored.join("、")}。asOf 会由服务端用于选择点时快照。`;
}
