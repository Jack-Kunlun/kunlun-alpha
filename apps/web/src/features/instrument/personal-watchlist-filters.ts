import { isPersonalWatchlistCode, type PersonalWatchlistItem } from "./personal-watchlist";

export const PERSONAL_WATCHLIST_MARKETS = [
  { value: "ALL", label: "全部市场" },
  { value: "SH", label: "上海（.SH）" },
  { value: "SZ", label: "深圳（.SZ）" },
  { value: "BJ", label: "北京（.BJ）" },
  { value: "OBSERVATION", label: "未接入观察项" },
] as const;

export type PersonalWatchlistMarketFilter = (typeof PERSONAL_WATCHLIST_MARKETS)[number]["value"];

interface PersonalWatchlistFilters {
  market: PersonalWatchlistMarketFilter;
  query: string;
}

function marketForCode(code: string): Exclude<PersonalWatchlistMarketFilter, "ALL"> | null {
  if (!isPersonalWatchlistCode(code)) return null;
  if (code.endsWith(".SH")) return "SH";
  if (code.endsWith(".SZ")) return "SZ";
  if (code.endsWith(".BJ")) return "BJ";
  return "OBSERVATION";
}

/** Filter the complete saved list before counting and taking a page; keep server order. */
export function selectPersonalWatchlistPage<T extends PersonalWatchlistItem>(
  items: readonly T[],
  filters: PersonalWatchlistFilters,
  page: number,
): { items: T[]; matchedCount: number; currentPage: number; pageCount: number } {
  const query = filters.query.trim().toUpperCase();
  const matches = items.filter(
    (item) =>
      (filters.market === "ALL" || marketForCode(item.code) === filters.market) &&
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
