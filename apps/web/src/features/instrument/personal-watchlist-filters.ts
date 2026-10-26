import { isPersonalWatchlistCode, type PersonalWatchlistItem } from "./personal-watchlist";
import type { ServerWatchlistItem, WatchlistMarketState } from "@kunlun/shared-types";

export const PERSONAL_WATCHLIST_MARKETS = [
  { value: "ALL", label: "全部市场" },
  { value: "SH", label: "上海（.SH）" },
  { value: "SZ", label: "深圳（.SZ）" },
  { value: "BJ", label: "北京（.BJ）" },
  { value: "OBSERVATION", label: "未接入观察项" },
] as const;

export type PersonalWatchlistMarketFilter = (typeof PERSONAL_WATCHLIST_MARKETS)[number]["value"];

export const PERSONAL_WATCHLIST_TASK_STATUSES = [
  { value: "ALL", label: "全部任务" },
  { value: "PENDING", label: "等待采集" },
  { value: "RUNNING", label: "采集中" },
  { value: "SUCCEEDED", label: "采集完成" },
  { value: "EMPTY", label: "行情源暂无日线" },
  { value: "FAILED", label: "采集失败" },
  { value: "UNSUPPORTED", label: "未接入" },
] as const satisfies readonly { value: "ALL" | WatchlistMarketState["status"]; label: string }[];

export type PersonalWatchlistTaskFilter =
  (typeof PERSONAL_WATCHLIST_TASK_STATUSES)[number]["value"];

/** Counts the already validated complete server list, independently of local filters or quotes. */
export function countPersonalWatchlistTasks(
  items: readonly ServerWatchlistItem[],
): Record<WatchlistMarketState["status"], number> {
  const counts = { PENDING: 0, RUNNING: 0, SUCCEEDED: 0, EMPTY: 0, FAILED: 0, UNSUPPORTED: 0 };
  for (const item of items) counts[item.market.status] += 1;
  return counts;
}

interface PersonalWatchlistFilters {
  market: PersonalWatchlistMarketFilter;
  query: string;
  taskStatus?: PersonalWatchlistTaskFilter;
}

function marketForCode(code: string): Exclude<PersonalWatchlistMarketFilter, "ALL"> | null {
  if (!isPersonalWatchlistCode(code)) return null;
  if (code.endsWith(".SH")) return "SH";
  if (code.endsWith(".SZ")) return "SZ";
  if (code.endsWith(".BJ")) return "BJ";
  return "OBSERVATION";
}

/** Filter the complete saved list before counting and taking a page; keep server order. */
export function selectPersonalWatchlistPage<
  T extends PersonalWatchlistItem & { market?: Pick<WatchlistMarketState, "status"> },
>(
  items: readonly T[],
  filters: PersonalWatchlistFilters,
  page: number,
): { items: T[]; matchedCount: number; currentPage: number; pageCount: number } {
  const query = filters.query.trim().toUpperCase();
  const matches = items.filter(
    (item) =>
      (filters.market === "ALL" || marketForCode(item.code) === filters.market) &&
      (filters.taskStatus === undefined ||
        filters.taskStatus === "ALL" ||
        item.market?.status === filters.taskStatus) &&
      `${item.code} ${item.name}`.toUpperCase().includes(query),
  );
  const pageCount = Math.max(1, Math.ceil(matches.length / 20));
  const currentPage = Math.min(Math.max(0, Number.isSafeInteger(page) ? page : 0), pageCount - 1);
  return {
    items: matches.slice(currentPage * 20, (currentPage + 1) * 20),
    matchedCount: matches.length,
    currentPage,
    pageCount,
  };
}
