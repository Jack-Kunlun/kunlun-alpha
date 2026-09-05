import type { MarketCoverageObservedDay } from "@kunlun/shared-types";

import { isRfc3339Instant } from "../../common/rfc3339";
import type { MarketCoverageDaysQuery } from "./market-coverage-days.query";

export const MARKET_COVERAGE_DAYS_QUERY_LIMIT = 367;

export interface MarketCoverageDaysReadModel {
  query(filters: MarketCoverageDaysQuery, asOf: string): Promise<MarketCoverageObservedDay[]>;
}

export class UnavailableMarketCoverageDaysReadModel implements MarketCoverageDaysReadModel {
  async query(
    _filters: MarketCoverageDaysQuery,
    _asOf: string,
  ): Promise<MarketCoverageObservedDay[]> {
    throw new Error("market coverage days read model is not configured");
  }
}

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("invalid ClickHouse market coverage day row");
  }
  return value as Record<string, unknown>;
}

function text(value: Record<string, unknown>, field: string): string {
  const candidate = value[field];
  if (typeof candidate !== "string" || candidate.length === 0) {
    throw new Error("invalid ClickHouse market coverage day field: " + field);
  }
  return candidate;
}

function date(value: Record<string, unknown>, field: string): string {
  const candidate = text(value, field);
  if (!DATE_PATTERN.test(candidate)) {
    throw new Error("invalid ClickHouse market coverage day field: " + field);
  }
  const parsed = new Date(`${candidate}T00:00:00.000Z`);
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== candidate) {
    throw new Error("invalid ClickHouse market coverage day field: " + field);
  }
  return candidate;
}

export function marketCoverageInstantNanos(value: string): bigint {
  if (!isRfc3339Instant(value)) {
    throw new Error("invalid ClickHouse market coverage day timestamp");
  }
  const withoutFraction = value.replace(/\.\d+(?=(Z|[+-]))/, "");
  const milliseconds = Date.parse(withoutFraction);
  if (!Number.isSafeInteger(milliseconds)) {
    throw new Error("invalid ClickHouse market coverage day timestamp");
  }
  const fractionMatch = /\.(\d+)(?=(Z|[+-]))/.exec(value);
  const fraction = (fractionMatch?.[1] ?? "").padEnd(9, "0");
  return BigInt(Math.trunc(milliseconds / 1000)) * 1_000_000_000n + BigInt(fraction);
}

function instant(value: Record<string, unknown>, field: string, asOfNanos: bigint): string {
  const candidate = text(value, field);
  if (marketCoverageInstantNanos(candidate) > asOfNanos) {
    throw new Error("market coverage day timestamp is after asOf");
  }
  return candidate;
}

type MarketCoverageDayFieldNames = readonly [string, string, string, string];

export function parseMarketCoverageObservedDay(
  value: unknown,
  asOfNanos: bigint,
  fields: MarketCoverageDayFieldNames = [
    "date",
    "latestEventTime",
    "latestAvailableTime",
    "latestProcessingTime",
  ],
): MarketCoverageObservedDay {
  const input = record(value);
  return {
    date: date(input, fields[0]),
    latestEventTime: instant(input, fields[1], asOfNanos),
    latestAvailableTime: instant(input, fields[2], asOfNanos),
    latestProcessingTime: instant(input, fields[3], asOfNanos),
  };
}

export function validateMarketCoverageDays(
  value: unknown,
  filters: MarketCoverageDaysQuery,
  asOf: string,
): MarketCoverageObservedDay[] {
  if (!Array.isArray(value) || value.length > MARKET_COVERAGE_DAYS_QUERY_LIMIT - 1) {
    throw new Error("invalid or overlong market coverage days result");
  }
  const asOfNanos = marketCoverageInstantNanos(asOf);
  const days = value.map((item) => parseMarketCoverageObservedDay(item, asOfNanos));
  let previousDate: string | undefined;
  for (const day of days) {
    if (day.date < filters.dateFrom || day.date > filters.dateTo) {
      throw new Error("market coverage day is outside requested window");
    }
    if (previousDate !== undefined && day.date <= previousDate) {
      throw new Error("market coverage days are not strictly ascending");
    }
    previousDate = day.date;
  }
  return days;
}
