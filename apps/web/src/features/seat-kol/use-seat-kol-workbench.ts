import { apiClient } from "@/lib/api-client";
import { useApiQuery, type QueryResult } from "@/lib/use-api-query";
import type { SeatKolWorkbenchSnapshot } from "./types";

const API_PATH = "/v1/seat-kol/workbench";

export interface SeatKolWorkbenchFilters {
  entityType: "ALL" | "SEAT" | "KOL";
  reviewStatus: "ALL" | "UNREVIEWED" | "IN_REVIEW" | "APPROVED" | "REJECTED";
  query: string;
}

export function useSeatKolWorkbench(
  filters: SeatKolWorkbenchFilters,
  asOf: string,
): QueryResult<SeatKolWorkbenchSnapshot> {
  return useApiQuery(
    () =>
      apiClient.get<SeatKolWorkbenchSnapshot[]>(API_PATH, {
        asOf,
        entityType: filters.entityType,
        reviewStatus: filters.reviewStatus,
        query: filters.query,
      }),
    [asOf, filters.entityType, filters.reviewStatus, filters.query],
  );
}
