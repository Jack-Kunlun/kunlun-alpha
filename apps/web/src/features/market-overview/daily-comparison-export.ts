import { version as applicationVersion } from "../../../package.json";
import {
  buildDailyComparison,
  formatDailyComparisonChange,
  sortDailyComparisonRows,
  type DailyComparison,
  type DailyComparisonBar,
  type DailyComparisonOutcome,
  type DailyComparisonRow,
  type DailyComparisonSort,
} from "./daily-comparison";

function invalid(): never {
  throw new Error("对比结果与本次查询不一致或未通过校验");
}

function barFields(bar: DailyComparisonBar | null) {
  if (bar === null) return null;
  return {
    date: bar.date,
    eventTime: bar.eventTime,
    close: bar.close,
    amount: bar.amount,
    suspended: bar.suspended,
    availableTime: bar.availableTime,
    processingTime: bar.processingTime,
    source: bar.source,
    sourceVersion: bar.sourceVersion,
    dataVersion: bar.dataVersion,
  };
}

function rowFields(row: DailyComparisonRow) {
  if (row.changeHundredthsOfPercent !== null && typeof row.changeHundredthsOfPercent !== "bigint")
    invalid();
  return {
    instrumentId: row.instrumentId,
    name: row.name,
    status: row.status,
    latest: barFields(row.latest),
    previous: barFields(row.previous),
    dateAligned: row.dateAligned,
    changeHundredthsOfPercent: row.changeHundredthsOfPercent?.toString() ?? null,
    changePercent:
      row.changeHundredthsOfPercent === null
        ? null
        : formatDailyComparisonChange(row.changeHundredthsOfPercent),
    changeReason: row.changeReason,
  };
}

/** Reuse the existing model's PIT/decimal rules, rather than introducing another calculation. */
function verifiedComparison(data: DailyComparison, expectedAsOf: string): DailyComparison {
  if (
    !data ||
    data.requestedAsOf !== expectedAsOf ||
    !Array.isArray(data.rows) ||
    data.rows.length < 1 ||
    data.rows.length > 20
  )
    invalid();
  const seen = new Set<string>();
  const stocks = data.rows.map((row) => {
    if (
      !row ||
      typeof row.instrumentId !== "string" ||
      !/^\d{6}\.(SH|SZ|BJ)$/.test(row.instrumentId) ||
      seen.has(row.instrumentId) ||
      typeof row.name !== "string" ||
      row.name.trim().length === 0 ||
      row.name.length > 80
    )
      invalid();
    seen.add(row.instrumentId);
    return { instrumentId: row.instrumentId, name: row.name, sector: "" };
  });
  const outcomes: DailyComparisonOutcome[] = data.rows.map((row, index) => {
    const stock = stocks[index]!;
    if (row.status === "ERROR") return { stock, kind: "error" };
    if (row.status === "FORBIDDEN") return { stock, kind: "forbidden" };
    if (row.status === "INVALID") return { stock, kind: "response", value: {} };
    if (row.status !== "AVAILABLE" && row.status !== "EMPTY") invalid();
    const bars = [row.previous, row.latest].filter((bar) => bar !== null);
    return {
      stock,
      kind: "response",
      value: {
        schemaVersion: "instrument-bars-v1",
        dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
        instrumentId: stock.instrumentId,
        mode: "HISTORICAL",
        requestedAsOf: expectedAsOf,
        effectiveAsOf: expectedAsOf,
        interval: "DAILY",
        priceType: "RAW",
        status: row.status,
        barCount: bars.length,
        bars,
      },
    };
  });
  const verified = buildDailyComparison(expectedAsOf, outcomes, stocks);
  if (
    data.comparisonDate !== verified.comparisonDate ||
    data.baselineDate !== verified.baselineDate ||
    data.rows.some(
      (row, index) =>
        JSON.stringify(rowFields(row)) !== JSON.stringify(rowFields(verified.rows[index]!)),
    )
  )
    invalid();
  return verified;
}

/** A local research file; unknown extra properties are never included. */
export function prepareDailyComparisonSnapshot(
  data: DailyComparison,
  expectedAsOf: string,
  sort: DailyComparisonSort,
): { filename: string; json: string; sampleCount: number } {
  if (
    !["close", "change", "amount"].includes(sort.key) ||
    !["ascending", "descending"].includes(sort.direction)
  )
    invalid();
  const verified = verifiedComparison(data, expectedAsOf);
  const rows = sortDailyComparisonRows(verified, sort).map(rowFields);
  const document = {
    schemaVersion: "daily-comparison-snapshot-v1",
    calculationVersion: "visible-close-change-v1",
    applicationVersion,
    dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
    scope: "WATCHLIST_VISIBLE_PAGE",
    requestedAsOf: verified.requestedAsOf,
    comparisonDate: verified.comparisonDate,
    baselineDate: verified.baselineDate,
    sort: { key: sort.key, direction: sort.direction },
    sampleCount: rows.length,
    rows,
  };
  // The JSON retains the exact cutoff; the filename is only a portable millisecond label.
  const time = new Date(verified.requestedAsOf).toISOString().replaceAll(/[-:.]/g, "");
  return {
    filename: `daily-comparison-${time}-${rows.length}.json`,
    json: `${JSON.stringify(document, null, 2)}\n`,
    sampleCount: rows.length,
  };
}
