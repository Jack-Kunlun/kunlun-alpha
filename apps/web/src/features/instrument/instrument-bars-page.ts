import type { InstrumentDailyBar } from "@kunlun/shared-types";

const PAGE_SIZE = 10;

/** Only selects existing records; the API window remains in its original order. */
export function selectInstrumentBarsPage(
  bars: readonly InstrumentDailyBar[],
  date: string,
  requestedPage: number,
) {
  const matched = date === "" ? [...bars] : bars.filter((bar) => bar.date === date);
  matched.reverse();
  const pageCount = Math.max(1, Math.ceil(matched.length / PAGE_SIZE));
  const page = Math.max(0, Math.min(pageCount - 1, Math.trunc(requestedPage) || 0));
  return {
    rows: matched.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE),
    page,
    pageCount,
    matchedCount: matched.length,
  };
}
