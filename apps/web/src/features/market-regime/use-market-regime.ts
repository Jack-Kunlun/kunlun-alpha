import { apiClient } from "@/lib/api-client";
import { useApiQuery, type QueryResult, type QueryStatus } from "@/lib/use-api-query";
import type {
  MarketEmotionSnapshot,
  MarketRegimeData,
  SectorRotationEvent,
} from "./types";

export interface MarketRegimeFilters {
  date: string;
  algorithmVersion?: string;
  sectorId?: string;
}

export interface MarketRegimeResult {
  status: QueryStatus;
  data: MarketRegimeData | null;
  error: Error | null;
}

const SNAPSHOT_PATH = "/v1/emotion/snapshots";
const EVENT_PATH = "/v1/emotion/rotation-events";

export function replayQuery(filters: MarketRegimeFilters): Record<string, string> {
  const query: Record<string, string> = { date: filters.date };
  if (filters.algorithmVersion) query.algorithmVersion = filters.algorithmVersion;
  if (filters.sectorId) query.sectorId = filters.sectorId;
  return query;
}

export function combineReplayResults(
  snapshots: QueryResult<MarketEmotionSnapshot>,
  events: QueryResult<SectorRotationEvent>,
): MarketRegimeResult {
  if (snapshots.status === "forbidden" || events.status === "forbidden") {
    return { status: "forbidden", data: null, error: snapshots.error ?? events.error };
  }
  if (snapshots.status === "error" || events.status === "error") {
    return { status: "error", data: null, error: snapshots.error ?? events.error };
  }
  if (snapshots.status === "loading" || events.status === "loading") {
    return { status: "loading", data: null, error: null };
  }
  const data = { snapshots: snapshots.data ?? [], events: events.data ?? [] };
  return {
    status: data.snapshots.length === 0 && data.events.length === 0 ? "empty" : "success",
    data,
    error: null,
  };
}

export function useMarketRegime(filters: MarketRegimeFilters): MarketRegimeResult {
  const query = replayQuery(filters);
  const dependencies = [filters.date, filters.algorithmVersion, filters.sectorId];
  const snapshots = useApiQuery(
    () => apiClient.get<MarketEmotionSnapshot[]>(SNAPSHOT_PATH, query),
    dependencies,
  );
  const events = useApiQuery(
    () => apiClient.get<SectorRotationEvent[]>(EVENT_PATH, query),
    dependencies,
  );
  return combineReplayResults(snapshots, events);
}
