import type { MarketCoverageSource, MarketQualityStatus } from "@kunlun/shared-types";
import type { DataQualityFilters } from "./use-data-quality";

export const MARKET_COVERAGE_SOURCES: readonly MarketCoverageSource[] = [
  "tushare-pro",
  "akshare-tencent",
  "akshare-sina",
  "akshare-eastmoney",
];

export interface DataQualityFilterDraft {
  date: string;
  source: string;
  unifiedCode: string;
  status: string;
}

export type DataQualityFilterErrors = Partial<Record<keyof DataQualityFilterDraft, string>>;

export type DataQualityFilterValidation =
  | {
      ok: true;
      filters: DataQualityFilters;
      status: MarketQualityStatus | undefined;
    }
  | {
      ok: false;
      filters: null;
      errors: DataQualityFilterErrors;
    };

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const CODE_PATTERN = /^\d{6}\.(SH|SZ|BJ)$/;
const EVIDENCE_STATUSES = [
  "REJECTED",
  "FILTERED",
] as const satisfies readonly MarketQualityStatus[];

function isCivilDate(value: string): boolean {
  if (!DATE_PATTERN.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  if (
    year === undefined ||
    month === undefined ||
    day === undefined ||
    year < 1 ||
    month < 1 ||
    month > 12
  ) {
    return false;
  }
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day >= 1 && day <= days[month - 1]!;
}

export function validateDataQualityFilters(
  draft: DataQualityFilterDraft,
): DataQualityFilterValidation {
  const errors: DataQualityFilterErrors = {};
  const date = draft.date.trim();
  const source = draft.source.trim();
  const unifiedCode = draft.unifiedCode.trim().toUpperCase();
  const status = draft.status.trim();

  if (date !== "" && !isCivilDate(date)) errors.date = "请输入有效的交易日";
  if (source !== "" && !MARKET_COVERAGE_SOURCES.includes(source as MarketCoverageSource)) {
    errors.source = "请选择支持的行情来源";
  }
  if (unifiedCode !== "" && !CODE_PATTERN.test(unifiedCode)) {
    errors.unifiedCode = "证券代码格式应为 600519.SH";
  }
  if (status !== "" && !EVIDENCE_STATUSES.includes(status as MarketQualityStatus)) {
    errors.status = "请选择有效的证据状态";
  }

  if (Object.keys(errors).length > 0) return { ok: false, filters: null, errors };

  const filters: DataQualityFilters = {};
  if (date !== "") filters.date = date;
  if (source !== "") filters.source = source;
  if (unifiedCode !== "") filters.unifiedCode = unifiedCode;
  return {
    ok: true,
    filters,
    status: status === "" ? undefined : (status as MarketQualityStatus),
  };
}
