import type { MarketCoverageResponse } from "@kunlun/shared-types";

type CoverageRow = MarketCoverageResponse["rows"][number];
const PAGE_SIZE = 20;

/** Browse only validated groups returned by this read, preserving server order. */
export function selectMarketCoveragePage(
  rows: readonly CoverageRow[],
  query: string,
  pageIndex: number,
): { rows: CoverageRow[]; matchedCount: number; currentPage: number; pageCount: number } {
  const search = query.trim().toLowerCase();
  const matches = rows.filter((row) =>
    `${row.unifiedCode} ${row.source}`.toLowerCase().includes(search),
  );
  const pageCount = Math.max(1, Math.ceil(matches.length / PAGE_SIZE));
  const currentPage = Math.min(
    Math.max(0, Number.isSafeInteger(pageIndex) ? pageIndex : 0),
    pageCount - 1,
  );
  return {
    rows: matches.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE),
    matchedCount: matches.length,
    currentPage,
    pageCount,
  };
}
