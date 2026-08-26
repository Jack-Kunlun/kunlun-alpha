import { ForbiddenException, Inject, Injectable } from "@nestjs/common";
import type { MarketOverviewSnapshot } from "@kunlun/shared-types";
import { DenyAllDashboardAuthorizer, type DashboardAuthorizer } from "./dashboard-authorizer";
import { validateMarketOverviewQuery } from "./dashboard-query";
import type { DashboardRepository, MarketOverviewRepositoryData } from "./dashboard-repository";
import { DASHBOARD_AUTHORIZER, DASHBOARD_REPOSITORY } from "./dashboard.tokens";

const DELAYED_AFTER_SECONDS = 90;
const STALE_AFTER_SECONDS = 300;

function dataTimes(data: MarketOverviewRepositoryData): string[] {
  return [
    ...data.indices.map((item) => item.dataTime),
    ...(data.breadth === null ? [] : [data.breadth.dataTime]),
    ...(data.turnover === null ? [] : [data.turnover.dataTime]),
    ...(data.emotion === null ? [] : [data.emotion.dataTime]),
  ];
}

function riskOf(
  data: MarketOverviewRepositoryData,
  mode: MarketOverviewSnapshot["mode"],
  requestedAsOf: string,
): MarketOverviewSnapshot["risk"] {
  const base = {
    basisVersion: "market-risk-temperature-v1" as const,
    dataMeaning: "RESEARCH_CONTEXT_NOT_ORDER_RISK" as const,
  };
  if (data.emotion === null) {
    return { ...base, state: "UNKNOWN", explanation: "缺少情绪快照，无法判断市场风险温度" };
  }
  const ageSeconds = Math.max(
    0,
    Math.floor((Date.parse(requestedAsOf) - Date.parse(data.emotion.dataTime)) / 1000),
  );
  if (mode === "CURRENT" && ageSeconds > STALE_AFTER_SECONDS) {
    return { ...base, state: "UNKNOWN", explanation: "情绪快照已过期，不用于当前风险判断" };
  }
  if (data.emotion.scoreBps >= 6500) {
    return { ...base, state: "CALM", explanation: "情绪得分处于稳健区间，仅作研究参考" };
  }
  if (data.emotion.scoreBps >= 4000) {
    return { ...base, state: "WATCH", explanation: "情绪得分进入观察区间，需结合证据复核" };
  }
  return { ...base, state: "STRESSED", explanation: "情绪得分处于压力区间，不代表订单风控结论" };
}

@Injectable()
export class DashboardService {
  constructor(
    @Inject(DASHBOARD_REPOSITORY) private readonly repository: DashboardRepository,
    @Inject(DASHBOARD_AUTHORIZER)
    private readonly authorizer: DashboardAuthorizer = new DenyAllDashboardAuthorizer(),
  ) {}

  async marketOverview(input: unknown): Promise<MarketOverviewSnapshot> {
    if (!(await this.authorizer.canAccess())) {
      throw new ForbiddenException("无权访问市场总览");
    }
    const query = validateMarketOverviewQuery(input);
    const data = await this.repository.loadMarketOverview(query.asOf);
    const times = dataTimes(data).sort();
    if (
      times.some(
        (value) => !Number.isFinite(Date.parse(value)) || Date.parse(value) > Date.parse(query.asOf),
      )
    ) {
      throw new Error("dashboard repository violated point-in-time cutoff");
    }
    const dataCutoffTime = times[0] ?? null;
    const ageSeconds =
      dataCutoffTime === null
        ? null
        : Math.max(0, Math.floor((Date.parse(query.asOf) - Date.parse(dataCutoffTime)) / 1000));
    let status: MarketOverviewSnapshot["freshness"]["status"] = "NO_DATA";
    if (dataCutoffTime !== null && query.mode === "HISTORICAL") status = "HISTORICAL";
    if (dataCutoffTime !== null && query.mode === "CURRENT" && ageSeconds !== null) {
      status =
        ageSeconds <= DELAYED_AFTER_SECONDS
          ? "FRESH"
          : ageSeconds <= STALE_AFTER_SECONDS
            ? "DELAYED"
            : "STALE";
    }
    const completedRegions = [
      data.indices.length > 0,
      data.breadth !== null,
      data.turnover !== null,
      data.emotion !== null,
    ].filter(Boolean).length;
    const completeness =
      completedRegions === 0 ? "EMPTY" : completedRegions === 4 ? "COMPLETE" : "PARTIAL";
    return {
      schemaVersion: "market-overview-v1",
      mode: query.mode,
      requestedAsOf: query.asOf,
      dataCutoffTime,
      completeness,
      freshness: {
        status,
        ageSeconds,
        delayedAfterSeconds: DELAYED_AFTER_SECONDS,
        staleAfterSeconds: STALE_AFTER_SECONDS,
      },
      indices: data.indices,
      breadth: data.breadth,
      turnover: data.turnover,
      emotion: data.emotion,
      risk: riskOf(data, query.mode, query.asOf),
      sourceVersions: data.sourceVersions,
      evidenceIds: data.evidenceIds,
      dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
    };
  }
}
