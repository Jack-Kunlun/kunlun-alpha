import type { MarketQualityEvidenceDetail, MarketQualityEvidencePage } from "@kunlun/shared-types";
import { apiClient } from "@/lib/api-client";
import { useApiObjectQuery, type ObjectQueryResult } from "@/lib/use-api-query";
import {
  parseMarketQualityEvidenceDetail,
  parseMarketQualityEvidencePage,
} from "./market-quality-evidence";

const API_PATH = "/v1/data-quality/market-evidence";

export interface MarketQualityEvidenceFilters {
  date?: string;
  start?: string;
  end?: string;
  source?: string;
  unifiedCode?: string;
  status?: string;
}

export interface MarketQualityEvidencePageOptions {
  snapshotId?: string | null;
  offset?: number;
  limit?: number;
}

function queryFor(
  filters: MarketQualityEvidenceFilters,
  options: MarketQualityEvidencePageOptions,
): Record<string, string> {
  const query: Record<string, string> = {};
  if (filters.source) query.source = filters.source;
  if (filters.unifiedCode) query.unifiedCode = filters.unifiedCode;
  if (filters.status) query.status = filters.status;
  if (filters.start && filters.end) {
    query.start = filters.start;
    query.end = filters.end;
  } else if (filters.date) {
    query.start = filters.date;
    query.end = filters.date;
  }
  if (options.snapshotId) query.snapshotId = options.snapshotId;
  if (options.offset !== undefined) query.offset = String(options.offset);
  if (options.limit !== undefined) query.limit = String(options.limit);
  return query;
}

export function useMarketQualityEvidence(
  filters: MarketQualityEvidenceFilters,
  options: MarketQualityEvidencePageOptions = {},
): ObjectQueryResult<MarketQualityEvidencePage> {
  const offset = options.offset ?? 0;
  const limit = options.limit ?? 20;
  const snapshotId = options.snapshotId ?? null;
  return useApiObjectQuery(
    () =>
      apiClient
        .get<unknown>(API_PATH, queryFor(filters, { snapshotId, offset, limit }))
        .then(parseMarketQualityEvidencePage),
    [
      filters.date,
      filters.start,
      filters.end,
      filters.source,
      filters.unifiedCode,
      filters.status,
      snapshotId,
      offset,
      limit,
    ],
  );
}

export function useMarketQualityEvidenceDetail(
  opaqueId: string | null,
  snapshotId: string | null,
): ObjectQueryResult<MarketQualityEvidenceDetail> {
  return useApiObjectQuery(
    () =>
      apiClient
        .get<unknown>(`${API_PATH}/${encodeURIComponent(opaqueId ?? "")}`, {
          snapshotId: snapshotId ?? "",
        })
        .then(parseMarketQualityEvidenceDetail),
    [opaqueId, snapshotId],
    opaqueId !== null && snapshotId !== null,
  );
}
