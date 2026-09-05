import type { MarketCoverageDaysResponse, MarketCoverageSource } from "@kunlun/shared-types";

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const CODE = /^\d{6}\.(SH|SZ|BJ)$/;
const SOURCE_VALUES = [
  "tushare-pro",
  "akshare-tencent",
  "akshare-sina",
  "akshare-eastmoney",
] as const;
const RFC3339 = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$/;
const MAX_DAYS = 366;
const MAX_TEXT = 256;
const DAY_NANOS = 86_400_000_000_000n;

export interface MarketCoverageDaysQuery {
  dateFrom: string;
  dateTo: string;
  unifiedCode: string;
  source: MarketCoverageSource;
}

export interface MarketCoverageDaysSelection extends MarketCoverageDaysQuery {
  /** Client-only identity used to invalidate details when the summary refreshes. */
  selectionKey?: string;
}

export class MarketCoverageDaysResponseError extends Error {
  constructor() {
    super("行情日明细响应格式无效");
    this.name = "MarketCoverageDaysResponseError";
  }
}

function invalid(): never {
  throw new MarketCoverageDaysResponseError();
}

function object(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) invalid();
  return value as Record<string, unknown>;
}

function exact(value: unknown, keys: readonly string[]): Record<string, unknown> {
  const result = object(value);
  const expected = new Set(keys);
  const actual = Object.keys(result);
  if (actual.length !== keys.length || actual.some((key) => !expected.has(key))) invalid();
  return result;
}

function text(value: unknown, max = MAX_TEXT): string {
  if (typeof value !== "string" || value.length === 0 || value.length > max) invalid();
  return value;
}

function legalDate(value: unknown): string {
  const candidate = text(value, 10);
  if (!DATE.test(candidate)) invalid();
  const [yearText, monthText, dayText] = candidate.split("-");
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    invalid();
  }
  return candidate;
}

function parseInstant(value: unknown): { text: string; nanos: bigint } {
  const candidate = text(value);
  const match = RFC3339.exec(candidate);
  if (match === null) invalid();
  const [yearText, monthText, dayText] = match[1]!.split("-");
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hour = Number(match[2]);
  const minute = Number(match[3]);
  const second = Number(match[4]);
  const offset = match[6]!;
  const offsetHour = offset === "Z" ? 0 : Number(offset.slice(1, 3));
  const offsetMinute = offset === "Z" ? 0 : Number(offset.slice(4, 6));
  const date = new Date(Date.UTC(year, month - 1, day));
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day ||
    hour > 23 ||
    minute > 59 ||
    second > 59 ||
    offsetHour > 23 ||
    offsetMinute > 59
  ) {
    invalid();
  }
  const milliseconds = Date.parse(`${match[1]}T${match[2]}:${match[3]}:${match[4]}.000${offset}`);
  if (!Number.isFinite(milliseconds)) invalid();
  const fraction = (match[5] ?? "").padEnd(9, "0");
  return {
    text: candidate,
    nanos: BigInt(milliseconds) * 1_000_000n + BigInt(fraction),
  };
}

function daysBetweenInclusive(dateFrom: string, dateTo: string): number {
  return (
    (Date.parse(`${dateTo}T00:00:00.000Z`) - Date.parse(`${dateFrom}T00:00:00.000Z`)) /
      Number(DAY_NANOS / 1_000_000n) +
    1
  );
}

export function buildMarketCoverageDaysQuery(
  query: MarketCoverageDaysQuery,
): Record<string, string> {
  return {
    dateFrom: query.dateFrom,
    dateTo: query.dateTo,
    unifiedCode: query.unifiedCode,
    source: query.source,
  };
}

export function parseMarketCoverageDaysResponse(value: unknown): MarketCoverageDaysResponse {
  const input = exact(value, [
    "schemaVersion",
    "scope",
    "meaning",
    "window",
    "unifiedCode",
    "source",
    "days",
  ]);
  if (
    input.schemaVersion !== "market-data-coverage-days-v1" ||
    input.scope !== "DAILY_RAW_SINGLE_SUPPORTED_SOURCE" ||
    input.meaning !== "OBSERVED_ONLY"
  ) {
    invalid();
  }
  const window = exact(input.window, ["dateFrom", "dateTo", "asOf"]);
  const dateFrom = legalDate(window.dateFrom);
  const dateTo = legalDate(window.dateTo);
  if (dateFrom > dateTo || daysBetweenInclusive(dateFrom, dateTo) > MAX_DAYS) invalid();
  const asOf = parseInstant(window.asOf);
  const unifiedCode = text(input.unifiedCode, 10);
  if (!CODE.test(unifiedCode)) invalid();
  const source = text(input.source);
  if (!SOURCE_VALUES.includes(source as MarketCoverageSource)) invalid();
  if (!Array.isArray(input.days) || input.days.length > MAX_DAYS) invalid();

  const days = input.days.map((value) => {
    const day = exact(value, [
      "date",
      "latestEventTime",
      "latestAvailableTime",
      "latestProcessingTime",
    ]);
    const date = legalDate(day.date);
    if (date < dateFrom || date > dateTo) invalid();
    const latestEventTime = parseInstant(day.latestEventTime);
    const latestAvailableTime = parseInstant(day.latestAvailableTime);
    const latestProcessingTime = parseInstant(day.latestProcessingTime);
    if (
      latestEventTime.nanos > asOf.nanos ||
      latestAvailableTime.nanos > asOf.nanos ||
      latestProcessingTime.nanos > asOf.nanos
    ) {
      invalid();
    }
    return {
      date,
      latestEventTime: latestEventTime.text,
      latestAvailableTime: latestAvailableTime.text,
      latestProcessingTime: latestProcessingTime.text,
    };
  });
  for (let index = 1; index < days.length; index += 1) {
    if (days[index - 1]!.date >= days[index]!.date) invalid();
  }
  return {
    schemaVersion: "market-data-coverage-days-v1",
    scope: "DAILY_RAW_SINGLE_SUPPORTED_SOURCE",
    meaning: "OBSERVED_ONLY",
    window: {
      dateFrom,
      dateTo,
      asOf: asOf.text,
    },
    unifiedCode,
    source: source as MarketCoverageSource,
    days,
  } as MarketCoverageDaysResponse;
}
