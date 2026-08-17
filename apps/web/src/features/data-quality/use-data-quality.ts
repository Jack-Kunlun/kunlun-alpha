/**
 * Data-quality query hook built on the shared ApiClient and useApiQuery.
 */

import { apiClient } from "@/lib/api-client";
import { useApiQuery, type QueryResult } from "@/lib/use-api-query";
import type { DataQualityRecord } from "./types";

export interface DataQualityFilters {
  date?: string;
  source?: string;
  unifiedCode?: string;
  kind?: string;
}

const API_PATH = "/v1/data-quality";

export function useDataQuality(filters: DataQualityFilters): QueryResult<DataQualityRecord> {
  const query: Record<string, string> = {};
  if (filters.date !== undefined && filters.date !== "") query.date = filters.date;
  if (filters.source !== undefined && filters.source !== "") query.source = filters.source;
  if (filters.unifiedCode !== undefined && filters.unifiedCode !== "") query.unifiedCode = filters.unifiedCode;
  if (filters.kind !== undefined && filters.kind !== "") query.kind = filters.kind;

  return useApiQuery(
    () => apiClient.get<DataQualityRecord[]>(API_PATH, query),
    [filters.date, filters.source, filters.unifiedCode, filters.kind],
  );
}

/** Safe internal evidence endpoint — never a raw object path. */
export function evidenceUrl(recordId: string): string {
  return `${API_PATH}/${encodeURIComponent(recordId)}/evidence`;
}
