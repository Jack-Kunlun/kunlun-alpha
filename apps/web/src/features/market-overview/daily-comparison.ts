import type { InstrumentDailyBar } from "@kunlun/shared-types";
import {
  LOCAL_TERMINAL_STOCKS,
  type LocalTerminalStock,
} from "../instrument/local-terminal-stock-samples";

export type DailyComparisonBar = Pick<
  InstrumentDailyBar,
  | "date"
  | "eventTime"
  | "close"
  | "amount"
  | "suspended"
  | "availableTime"
  | "processingTime"
  | "source"
  | "sourceVersion"
  | "dataVersion"
>;

export type DailyComparisonRowStatus = "AVAILABLE" | "EMPTY" | "ERROR" | "FORBIDDEN" | "INVALID";

export interface DailyComparisonRow {
  instrumentId: string;
  name: string;
  sector: string;
  status: DailyComparisonRowStatus;
  latest: DailyComparisonBar | null;
  previous: DailyComparisonBar | null;
  dateAligned: boolean;
  changeHundredthsOfPercent: bigint | null;
  changeReason: string | null;
}

export interface DailyComparison {
  requestedAsOf: string;
  comparisonDate: string | null;
  baselineDate: string | null;
  rows: readonly DailyComparisonRow[];
}

export type DailyComparisonOutcome =
  | { stock: LocalTerminalStock; kind: "response"; value: unknown }
  | { stock: LocalTerminalStock; kind: "error" }
  | { stock: LocalTerminalStock; kind: "forbidden" };

export type DailyComparisonSortKey = "close" | "change" | "amount";
export type DailyComparisonSortDirection = "ascending" | "descending";

export interface DailyComparisonSort {
  key: DailyComparisonSortKey;
  direction: DailyComparisonSortDirection;
}

interface ParsedDecimal {
  coefficient: bigint;
  scale: number;
}

const DECIMAL = /^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
const RFC3339_INSTANT =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|([+-])(\d{2}):(\d{2}))$/;
const MAX_DECIMAL_LENGTH = 256;
const SHANGHAI_DATE_FORMATTER = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function dateOnly(value: unknown): value is string {
  if (typeof value !== "string" || !DATE_ONLY.test(value)) return false;
  const date = new Date(`${value}T00:00:00.000Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

function instant(value: unknown): number {
  if (typeof value !== "string") throw new Error("invalid timestamp");
  const match = RFC3339_INSTANT.exec(value);
  if (match === null) throw new Error("invalid timestamp");
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  const zone = match[8];
  const offsetHour = match[10] === undefined ? 0 : Number(match[10]);
  const offsetMinute = match[11] === undefined ? 0 : Number(match[11]);
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (
    year === 0 ||
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > (daysInMonth[month - 1] ?? 0) ||
    hour > 23 ||
    minute > 59 ||
    second > 59 ||
    offsetHour > 23 ||
    offsetMinute > 59 ||
    zone === "-00:00"
  ) {
    throw new Error("invalid timestamp");
  }
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) throw new Error("invalid timestamp");
  return timestamp;
}

function shanghaiDate(timestamp: number): string {
  const parts = SHANGHAI_DATE_FORMATTER.formatToParts(new Date(timestamp));
  const part = (type: Intl.DateTimeFormatPartTypes): string =>
    parts.find((value) => value.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function parseDecimal(value: unknown): ParsedDecimal {
  if (typeof value !== "string" || value.length > MAX_DECIMAL_LENGTH || !DECIMAL.test(value)) {
    throw new Error("invalid decimal");
  }
  const [whole = "0", fraction = ""] = value.split(".");
  return { coefficient: BigInt(whole + fraction), scale: fraction.length };
}

function aligned(left: ParsedDecimal, right: ParsedDecimal): [bigint, bigint] {
  const scale = Math.max(left.scale, right.scale);
  return [
    left.coefficient * 10n ** BigInt(scale - left.scale),
    right.coefficient * 10n ** BigInt(scale - right.scale),
  ];
}

function compareDecimal(left: string, right: string): number {
  const [leftValue, rightValue] = aligned(parseDecimal(left), parseDecimal(right));
  return leftValue < rightValue ? -1 : leftValue > rightValue ? 1 : 0;
}

function compareInstantNoLater(value: unknown, cutoff: number): void {
  if (instant(value) > cutoff) throw new Error("future timestamp");
}

function parseBar(value: unknown, cutoff: number, cutoffShanghaiDate: string): DailyComparisonBar {
  if (!isRecord(value)) throw new Error("invalid daily bar");
  if (!dateOnly(value["date"])) throw new Error("invalid daily bar date");
  if (value["date"] > cutoffShanghaiDate) throw new Error("future daily bar date");
  compareInstantNoLater(value["eventTime"], cutoff);
  compareInstantNoLater(value["availableTime"], cutoff);
  compareInstantNoLater(value["processingTime"], cutoff);
  parseDecimal(value["close"]);
  parseDecimal(value["amount"]);
  if (typeof value["suspended"] !== "boolean") throw new Error("invalid suspended flag");
  if (
    !nonEmptyString(value["source"]) ||
    !nonEmptyString(value["sourceVersion"]) ||
    !nonEmptyString(value["dataVersion"])
  ) {
    throw new Error("invalid provenance");
  }

  return {
    date: value["date"],
    eventTime: value["eventTime"] as string,
    close: value["close"] as string,
    amount: value["amount"] as string,
    suspended: value["suspended"],
    availableTime: value["availableTime"] as string,
    processingTime: value["processingTime"] as string,
    source: value["source"],
    sourceVersion: value["sourceVersion"],
    dataVersion: value["dataVersion"],
  };
}

function parseResponse(
  value: unknown,
  expectedInstrumentId: string,
  expectedAsOf: string,
): readonly DailyComparisonBar[] {
  const cutoff = instant(expectedAsOf);
  if (!isRecord(value)) throw new Error("invalid bars response");
  if (
    value["schemaVersion"] !== "instrument-bars-v1" ||
    value["dataMeaning"] !== "RESEARCH_ONLY_NO_REAL_ORDER_PATH" ||
    value["instrumentId"] !== expectedInstrumentId ||
    value["mode"] !== "HISTORICAL" ||
    value["interval"] !== "DAILY" ||
    value["priceType"] !== "RAW"
  ) {
    throw new Error("mismatched bars response");
  }
  if (
    typeof value["requestedAsOf"] !== "string" ||
    instant(value["requestedAsOf"]) !== cutoff ||
    typeof value["effectiveAsOf"] !== "string" ||
    instant(value["effectiveAsOf"]) !== cutoff
  ) {
    throw new Error("mismatched point-in-time response");
  }
  if (!Array.isArray(value["bars"]) || value["bars"].length > 2) {
    throw new Error("invalid bars array");
  }
  if (typeof value["barCount"] !== "number" || value["barCount"] !== value["bars"].length) {
    throw new Error("mismatched bars count");
  }
  const cutoffShanghaiDate = shanghaiDate(cutoff);
  const bars = value["bars"].map((bar) => parseBar(bar, cutoff, cutoffShanghaiDate));
  for (let index = 1; index < bars.length; index += 1) {
    const previous = bars[index - 1];
    const current = bars[index];
    if (previous === undefined || current === undefined || previous.date >= current.date) {
      throw new Error("daily bars must have unique ascending dates");
    }
  }
  if (
    (value["status"] === "EMPTY" && bars.length !== 0) ||
    (value["status"] === "AVAILABLE" && bars.length === 0) ||
    (value["status"] !== "EMPTY" && value["status"] !== "AVAILABLE")
  ) {
    throw new Error("mismatched bars status");
  }
  return bars;
}

function makeRow(
  stock: LocalTerminalStock,
  status: DailyComparisonRowStatus,
  latest: DailyComparisonBar | null = null,
  previous: DailyComparisonBar | null = null,
): DailyComparisonRow {
  return {
    instrumentId: stock.instrumentId,
    name: stock.name,
    sector: stock.sector,
    status,
    latest,
    previous,
    dateAligned: false,
    changeHundredthsOfPercent: null,
    changeReason: null,
  };
}

function roundedDivision(numerator: bigint, denominator: bigint): bigint {
  const negative = numerator < 0n;
  const absolute = negative ? -numerator : numerator;
  const rounded = (absolute + denominator / 2n) / denominator;
  return negative ? -rounded : rounded;
}

function calculateChange(previous: string, current: string): bigint {
  const [previousValue, currentValue] = aligned(parseDecimal(previous), parseDecimal(current));
  return roundedDivision((currentValue - previousValue) * 10_000n, previousValue);
}

function rowChange(
  row: DailyComparisonRow,
  comparisonDate: string | null,
  baselineDate: string | null,
): Pick<DailyComparisonRow, "dateAligned" | "changeHundredthsOfPercent" | "changeReason"> {
  if (row.status !== "AVAILABLE" || row.latest === null) {
    return { dateAligned: false, changeHundredthsOfPercent: null, changeReason: null };
  }
  if (row.latest.date !== comparisonDate) {
    return {
      dateAligned: false,
      changeHundredthsOfPercent: null,
      changeReason: "行情日期不一致",
    };
  }
  if (row.previous === null) {
    return {
      dateAligned: true,
      changeHundredthsOfPercent: null,
      changeReason: "缺少前一可见日线",
    };
  }
  if (row.previous.date !== baselineDate) {
    return {
      dateAligned: true,
      changeHundredthsOfPercent: null,
      changeReason: "基准日期不一致",
    };
  }
  if (
    row.latest.source !== row.previous.source ||
    row.latest.sourceVersion !== row.previous.sourceVersion
  ) {
    return {
      dateAligned: true,
      changeHundredthsOfPercent: null,
      changeReason: "来源版本不一致",
    };
  }
  if (row.latest.dataVersion !== row.previous.dataVersion) {
    return {
      dateAligned: true,
      changeHundredthsOfPercent: null,
      changeReason: "数据版本不一致",
    };
  }
  if (parseDecimal(row.previous.close).coefficient === 0n) {
    return {
      dateAligned: true,
      changeHundredthsOfPercent: null,
      changeReason: "前收价无效",
    };
  }
  if (row.latest.suspended || row.previous.suspended) {
    return {
      dateAligned: true,
      changeHundredthsOfPercent: null,
      changeReason: "停牌，不计算涨跌幅",
    };
  }
  return {
    dateAligned: true,
    changeHundredthsOfPercent: calculateChange(row.previous.close, row.latest.close),
    changeReason: null,
  };
}

export function buildDailyComparison(
  requestedAsOf: string,
  outcomes: readonly DailyComparisonOutcome[],
): DailyComparison {
  instant(requestedAsOf);
  const outcomeByInstrument = new Map(
    outcomes.map((outcome) => [outcome.stock.instrumentId, outcome]),
  );
  const baseRows = LOCAL_TERMINAL_STOCKS.map((stock) => {
    const outcome = outcomeByInstrument.get(stock.instrumentId);
    if (outcome === undefined || outcome.kind === "error") return makeRow(stock, "ERROR");
    if (outcome.kind === "forbidden") return makeRow(stock, "FORBIDDEN");
    try {
      const bars = parseResponse(outcome.value, stock.instrumentId, requestedAsOf);
      if (bars.length === 0) return makeRow(stock, "EMPTY");
      return makeRow(stock, "AVAILABLE", bars.at(-1) ?? null, bars.at(-2) ?? null);
    } catch {
      return makeRow(stock, "INVALID");
    }
  });

  const comparisonDate = baseRows.reduce<string | null>((latestDate, row) => {
    if (row.status !== "AVAILABLE" || row.latest === null) return latestDate;
    return latestDate === null || row.latest.date > latestDate ? row.latest.date : latestDate;
  }, null);
  const baselineDate = baseRows.reduce<string | null>((latestDate, row) => {
    if (
      row.status !== "AVAILABLE" ||
      row.latest?.date !== comparisonDate ||
      row.previous === null
    ) {
      return latestDate;
    }
    return latestDate === null || row.previous.date > latestDate ? row.previous.date : latestDate;
  }, null);
  const rows = baseRows.map((row) => ({
    ...row,
    ...rowChange(row, comparisonDate, baselineDate),
  }));

  return { requestedAsOf, comparisonDate, baselineDate, rows };
}

function sortRank(row: DailyComparisonRow, comparisonDate: string | null): number {
  if (row.status === "AVAILABLE" && row.latest !== null) {
    return row.latest.date === comparisonDate ? 0 : 1;
  }
  return 2;
}

function sortValue(row: DailyComparisonRow, key: DailyComparisonSortKey): string | bigint | null {
  if (row.latest === null) return null;
  if (key === "close") return row.latest.close;
  if (key === "amount") return row.latest.amount;
  return row.changeHundredthsOfPercent;
}

export function sortDailyComparisonRows(
  comparison: DailyComparison,
  sort: DailyComparisonSort,
): readonly DailyComparisonRow[] {
  return comparison.rows
    .map((row, index) => ({ row, index }))
    .sort((left, right) => {
      const rankDifference =
        sortRank(left.row, comparison.comparisonDate) -
        sortRank(right.row, comparison.comparisonDate);
      if (rankDifference !== 0) return rankDifference;
      if (sortRank(left.row, comparison.comparisonDate) !== 0) return left.index - right.index;

      const leftValue = sortValue(left.row, sort.key);
      const rightValue = sortValue(right.row, sort.key);
      if (leftValue === null || rightValue === null) {
        if (leftValue === rightValue) return left.index - right.index;
        return leftValue === null ? 1 : -1;
      }
      let order: number;
      if (typeof leftValue === "bigint" && typeof rightValue === "bigint") {
        order = leftValue < rightValue ? -1 : leftValue > rightValue ? 1 : 0;
      } else if (typeof leftValue === "string" && typeof rightValue === "string") {
        order = compareDecimal(leftValue, rightValue);
      } else {
        order = 0;
      }
      if (sort.direction === "descending") order = -order;
      return order === 0 ? left.index - right.index : order;
    })
    .map(({ row }) => row);
}

export function formatDailyComparisonDecimal(value: string): string {
  if (value.length > MAX_DECIMAL_LENGTH || !DECIMAL.test(value)) return "—";
  const [whole = "0", fraction] = value.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return fraction === undefined ? grouped : `${grouped}.${fraction}`;
}

export function formatDailyComparisonChange(value: bigint | null): string {
  if (value === null) return "—";
  const sign = value > 0n ? "+" : value < 0n ? "-" : "";
  const absolute = value < 0n ? -value : value;
  return `${sign}${absolute / 100n}.${(absolute % 100n).toString().padStart(2, "0")}%`;
}
