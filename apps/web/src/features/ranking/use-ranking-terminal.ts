"use client";

import type { RankingTerminalSnapshot } from "@kunlun/shared-types";
import { apiClient, ApiError } from "@/lib/api-client";
import { useApiObjectQuery, type ObjectQueryResult } from "@/lib/use-api-query";
import type { RankingTerminalResult } from "./types";

export const RANKING_TERMINAL_PATH = "/v1/ranking/latest";

export function useRankingTerminal(asOf: string | null): RankingTerminalResult {
  const query = useApiObjectQuery(
    () =>
      apiClient.get<RankingTerminalSnapshot>(
        RANKING_TERMINAL_PATH,
        asOf === null ? undefined : { asOf },
      ),
    [asOf],
    true,
    asOf === null ? 60_000 : 0,
  );
  return rankingTerminalResult(query);
}

export function rankingTerminalResult(
  query: ObjectQueryResult<RankingTerminalSnapshot>,
): RankingTerminalResult {
  if (query.status === "loading") return { state: "loading" };
  if (query.status === "forbidden")
    return { state: "forbidden", message: "当前身份无权读取排名快照" };
  if (query.status === "error") {
    if (query.error instanceof ApiError && query.error.status === 404) {
      return { state: "empty", message: "当前没有已发布的 Ranking 快照" };
    }
    return { state: "error", message: query.error?.message ?? "Ranking 快照加载失败" };
  }
  if (query.data === null) return { state: "empty", message: "当前没有已发布的 Ranking 快照" };
  return { state: "success", snapshot: query.data };
}
