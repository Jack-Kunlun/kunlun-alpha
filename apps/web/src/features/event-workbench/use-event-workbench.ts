import { apiClient } from "@/lib/api-client";
import { useApiQuery, type QueryResult } from "@/lib/use-api-query";
import type { HotTopicSnapshot, MarketEvent } from "./types";

const API_PATH = "/v1/event-intelligence";

export interface EventWorkbenchFilters {
  dateFrom?: string;
  dateTo?: string;
  eventType?: string;
  instrumentId?: string;
  minimumConfidenceBps?: string;
}

export interface EventWorkbenchResult {
  events: QueryResult<MarketEvent>;
  topics: QueryResult<HotTopicSnapshot>;
}

export function useEventWorkbench(
  filters: EventWorkbenchFilters,
  asOf: string,
): EventWorkbenchResult {
  const eventQuery: Record<string, string> = {};
  for (const [key, value] of Object.entries(filters)) {
    if (value) eventQuery[key] = value;
  }
  const events = useApiQuery(
    () => apiClient.get<MarketEvent[]>(`${API_PATH}/events`, eventQuery),
    [
      filters.dateFrom,
      filters.dateTo,
      filters.eventType,
      filters.instrumentId,
      filters.minimumConfidenceBps,
    ],
  );
  const topics = useApiQuery(
    () => apiClient.get<HotTopicSnapshot[]>(`${API_PATH}/hot-topics`, { asOf }),
    [asOf],
  );
  return { events, topics };
}
