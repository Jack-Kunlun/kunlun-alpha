import type { MarketCoverageDaysQuery } from "./market-coverage-days";

export type MarketCoverageHistoryWindow = Pick<MarketCoverageDaysQuery, "dateFrom" | "dateTo">;
export type MarketCoverageHistoryErrors = Partial<
  Record<keyof MarketCoverageHistoryWindow, string>
>;

type WindowValidation =
  | { ok: true; window: MarketCoverageHistoryWindow }
  | { ok: false; errors: MarketCoverageHistoryErrors };

function isApiCivilDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  const parsed = new Date(Date.UTC(year!, month! - 1, day));
  return (
    parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month! - 1 &&
    parsed.getUTCDate() === day
  );
}

export function validateMarketCoverageHistoryWindow(
  draft: MarketCoverageHistoryWindow,
): WindowValidation {
  const dateFrom = draft.dateFrom.trim();
  const dateTo = draft.dateTo.trim();
  const errors: MarketCoverageHistoryErrors = {};
  if (dateFrom === "") errors.dateFrom = "请选择开始日期";
  else if (!isApiCivilDate(dateFrom)) errors.dateFrom = "请输入有效的开始日期";
  if (dateTo === "") errors.dateTo = "请选择结束日期";
  else if (!isApiCivilDate(dateTo)) errors.dateTo = "请输入有效的结束日期";
  if (Object.keys(errors).length > 0) return { ok: false, errors };

  if (dateFrom > dateTo) return { ok: false, errors: { dateTo: "结束日期不能早于开始日期" } };
  const inclusiveDays =
    (Date.parse(`${dateTo}T00:00:00.000Z`) - Date.parse(`${dateFrom}T00:00:00.000Z`)) / 86_400_000 +
    1;
  if (inclusiveDays > 366) {
    return { ok: false, errors: { dateTo: "查询窗口最多为 366 个自然日（含起止日）" } };
  }
  return { ok: true, window: { dateFrom, dateTo } };
}
