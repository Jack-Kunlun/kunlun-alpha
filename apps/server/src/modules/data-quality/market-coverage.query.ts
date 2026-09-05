const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const UNIFIED_CODE_PATTERN = /^\d{6}\.(SH|SZ|BJ)$/;
const SOURCE_VALUES = new Set([
  "tushare-pro",
  "akshare-tencent",
  "akshare-sina",
  "akshare-eastmoney",
]);
const ALLOWED_KEYS = new Set(["date", "dateFrom", "dateTo", "source", "unifiedCode"]);
const DAY_MS = 24 * 60 * 60 * 1000;
const DEFAULT_WINDOW_DAYS = 90;
const MAX_WINDOW_DAYS = 366;

export class MarketCoverageValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MarketCoverageValidationError";
  }
}

export interface MarketCoverageQuery {
  dateFrom: string;
  dateTo: string;
  source?: string;
  unifiedCode?: string;
}

export interface MarketCoverageClock {
  now(): Date;
}

export class SystemMarketCoverageClock implements MarketCoverageClock {
  now(): Date {
    return new Date();
  }
}

function asObject(input: unknown): Record<string, unknown> {
  if (typeof input !== "object" || input === null || Array.isArray(input)) {
    throw new MarketCoverageValidationError("query must be an object");
  }
  return input as Record<string, unknown>;
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== "string" || value.trim() === "") {
    throw new MarketCoverageValidationError(`${field} must be a non-empty string`);
  }
  return value;
}

function legalDate(value: unknown, field: string): string {
  const text = requiredString(value, field);
  if (!DATE_PATTERN.test(text)) {
    throw new MarketCoverageValidationError(`${field} must be a valid YYYY-MM-DD date`);
  }
  const [yearText, monthText, dayText] = text.split("-");
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  if (
    parsed.getUTCFullYear() !== year ||
    parsed.getUTCMonth() !== month - 1 ||
    parsed.getUTCDate() !== day
  ) {
    throw new MarketCoverageValidationError(`${field} must be a valid YYYY-MM-DD date`);
  }
  return text;
}

function formatDate(value: Date): string {
  return value.toISOString().slice(0, 10);
}

function shanghaiDate(value: Date): string {
  if (Number.isNaN(value.getTime())) {
    throw new MarketCoverageValidationError("coverage clock returned an invalid date");
  }
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(value);
  const fields = new Map(parts.map((part) => [part.type, part.value]));
  return `${fields.get("year") ?? ""}-${fields.get("month") ?? ""}-${fields.get("day") ?? ""}`;
}

function subtractDays(date: string, days: number): string {
  const value = new Date(`${date}T00:00:00.000Z`);
  value.setUTCDate(value.getUTCDate() - days);
  return formatDate(value);
}

function inclusiveDayCount(dateFrom: string, dateTo: string): number {
  return (
    (Date.parse(`${dateTo}T00:00:00.000Z`) - Date.parse(`${dateFrom}T00:00:00.000Z`)) / DAY_MS + 1
  );
}

/** Parse the strict market-coverage query, including its bounded default window. */
export function parseMarketCoverageQuery(input: unknown, now: Date): MarketCoverageQuery {
  const record = asObject(input);
  for (const key of Object.keys(record)) {
    if (!ALLOWED_KEYS.has(key)) {
      throw new MarketCoverageValidationError("unsupported market coverage query parameter");
    }
  }

  const hasDate = record.date !== undefined;
  const hasDateFrom = record.dateFrom !== undefined;
  const hasDateTo = record.dateTo !== undefined;
  if (hasDate && (hasDateFrom || hasDateTo)) {
    throw new MarketCoverageValidationError("date cannot be combined with dateFrom or dateTo");
  }
  if (hasDateFrom !== hasDateTo) {
    throw new MarketCoverageValidationError("dateFrom and dateTo must be provided together");
  }

  let dateFrom: string;
  let dateTo: string;
  if (hasDate) {
    dateFrom = legalDate(record.date, "date");
    dateTo = dateFrom;
  } else if (hasDateFrom && hasDateTo) {
    dateFrom = legalDate(record.dateFrom, "dateFrom");
    dateTo = legalDate(record.dateTo, "dateTo");
  } else {
    dateTo = shanghaiDate(now);
    dateFrom = subtractDays(dateTo, DEFAULT_WINDOW_DAYS - 1);
  }

  if (dateFrom > dateTo) {
    throw new MarketCoverageValidationError("dateFrom must not be after dateTo");
  }
  if (inclusiveDayCount(dateFrom, dateTo) > MAX_WINDOW_DAYS) {
    throw new MarketCoverageValidationError("coverage window must not exceed 366 calendar days");
  }

  const query: MarketCoverageQuery = { dateFrom, dateTo };
  if (record.source !== undefined) {
    const source = requiredString(record.source, "source");
    if (!SOURCE_VALUES.has(source)) {
      throw new MarketCoverageValidationError("source is not supported");
    }
    query.source = source;
  }
  if (record.unifiedCode !== undefined) {
    const unifiedCode = requiredString(record.unifiedCode, "unifiedCode");
    if (!UNIFIED_CODE_PATTERN.test(unifiedCode)) {
      throw new MarketCoverageValidationError(
        "unifiedCode must use suffix form like 600519.SH (legacy prefix form rejected)",
      );
    }
    query.unifiedCode = unifiedCode;
  }
  return query;
}

export const MARKET_COVERAGE_DEFAULT_WINDOW_DAYS = DEFAULT_WINDOW_DAYS;
export const MARKET_COVERAGE_MAX_WINDOW_DAYS = MAX_WINDOW_DAYS;
