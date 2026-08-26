import type {
  MarketOverviewBreadthMetric,
  MarketOverviewEmotionMetric,
  MarketOverviewIndexMetric,
  MarketOverviewTurnoverMetric,
} from "@kunlun/shared-types";

export interface MarketOverviewRepositoryData {
  indices: MarketOverviewIndexMetric[];
  breadth: MarketOverviewBreadthMetric | null;
  turnover: MarketOverviewTurnoverMetric | null;
  emotion: MarketOverviewEmotionMetric | null;
  sourceVersions: string[];
  evidenceIds: string[];
}

export interface DashboardRepository {
  loadMarketOverview(asOf: string): Promise<MarketOverviewRepositoryData>;
}
