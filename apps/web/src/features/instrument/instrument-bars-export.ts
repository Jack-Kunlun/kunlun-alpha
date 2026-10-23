import type { InstrumentBarsResponse, InstrumentDailyBar } from "@kunlun/shared-types";
import { isCanonicalInstrumentId } from "./use-instrument-intelligence";

const DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
const RFC3339_PATTERN =
  /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$/;
const NON_NEGATIVE_DECIMAL_PATTERN = /^\d+(?:\.\d+)?$/;
const FORMULA_PREFIX_PATTERN =
  /^[\u0000-\u0020\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*[=+\-@]/u;
const NANOS_PER_MILLISECOND = 1_000_000n;

const CSV_COLUMNS = [
  "instrumentId",
  "mode",
  "requestedAsOf",
  "effectiveAsOf",
  "dataCutoffTime",
  "interval",
  "priceType",
  "barCount",
  "schemaVersion",
  "dataMeaning",
  "status",
  "freshnessSeconds",
  "date",
  "eventTime",
  "open",
  "high",
  "low",
  "close",
  "volume",
  "amount",
  "suspended",
  "availableTime",
  "processingTime",
  "source",
  "sourceVersion",
  "dataVersion",
  "evidenceId",
] as const;

function invalid(reason: string): never {
  throw new Error(`日线 CSV 数据无效：${reason}`);
}

function isCivilDate(value: string): boolean {
  if (typeof value !== "string") return false;
  const match = DATE_PATTERN.exec(value);
  if (match === null) return false;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (year < 1 || month < 1 || month > 12) return false;

  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const monthDays = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day >= 1 && day <= monthDays[month - 1]!;
}

function instantNanoseconds(value: string): bigint | null {
  if (typeof value !== "string") return null;
  const match = RFC3339_PATTERN.exec(value);
  if (match === null || !isCivilDate(match[1]!)) return null;

  const hour = Number(match[2]);
  const minute = Number(match[3]);
  const second = Number(match[4]);
  const zone = match[6]!;
  if (hour > 23 || minute > 59 || second > 59 || zone === "-00:00") return null;

  const offsetHour = zone === "Z" ? 0 : Number(zone.slice(1, 3));
  const offsetMinute = zone === "Z" ? 0 : Number(zone.slice(4, 6));
  if (offsetHour > 23 || offsetMinute > 59) return null;

  const localMillis = Date.parse(`${match[1]}T${match[2]}:${match[3]}:${match[4]}.000Z`);
  if (!Number.isFinite(localMillis)) return null;
  const offsetMillis =
    (zone === "Z" ? 0 : (zone[0] === "+" ? 1 : -1) * (offsetHour * 60 + offsetMinute)) * 60_000;
  const fractionalNanos = BigInt((match[5] ?? "").padEnd(9, "0") || "0");
  return BigInt(localMillis - offsetMillis) * NANOS_PER_MILLISECOND + fractionalNanos;
}

function isNonEmptyText(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function requireTimestamp(value: string, field: string): bigint {
  const instant = instantNanoseconds(value);
  if (instant === null) return invalid(`${field} 必须是有效的带时区时间`);
  return instant;
}

function validateBar(bar: InstrumentDailyBar, effectiveAsOf: bigint, index: number): void {
  if (typeof bar !== "object" || bar === null || Array.isArray(bar)) {
    invalid(`第 ${index + 1} 根日线格式无效`);
  }
  if (!isCivilDate(bar.date)) invalid(`第 ${index + 1} 根日线日期无效`);

  for (const field of ["eventTime", "availableTime", "processingTime"] as const) {
    const value = requireTimestamp(bar[field], `第 ${index + 1} 根日线 ${field}`);
    if (value > effectiveAsOf) {
      invalid(`第 ${index + 1} 根日线 ${field} 晚于 effectiveAsOf`);
    }
  }

  for (const field of ["open", "high", "low", "close", "volume", "amount"] as const) {
    if (typeof bar[field] !== "string" || !NON_NEGATIVE_DECIMAL_PATTERN.test(bar[field])) {
      invalid(`第 ${index + 1} 根日线 ${field} 必须是非负十进制字符串`);
    }
  }

  if (typeof bar.suspended !== "boolean") invalid(`第 ${index + 1} 根日线 suspended 必须是布尔值`);
  for (const field of ["source", "sourceVersion", "dataVersion", "evidenceId"] as const) {
    if (!isNonEmptyText(bar[field])) invalid(`第 ${index + 1} 根日线缺少 ${field} 溯源`);
  }
}

function validateResponse(data: InstrumentBarsResponse): void {
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    invalid("响应格式无效");
  }
  if (data.schemaVersion !== "instrument-bars-v1") invalid("schemaVersion 不受支持");
  if (data.dataMeaning !== "RESEARCH_ONLY_NO_REAL_ORDER_PATH") invalid("dataMeaning 不受支持");
  if (data.interval !== "DAILY" || data.priceType !== "RAW") invalid("仅支持 DAILY RAW 日线");
  if (data.status !== "AVAILABLE") invalid("仅支持 AVAILABLE 日线窗口");
  if (typeof data.instrumentId !== "string" || !isCanonicalInstrumentId(data.instrumentId)) {
    invalid("instrumentId 不是规范证券代码");
  }
  if (data.mode !== "CURRENT" && data.mode !== "HISTORICAL") invalid("mode 不受支持");

  const requestedAsOf = requireTimestamp(data.requestedAsOf, "requestedAsOf");
  const effectiveAsOf = requireTimestamp(data.effectiveAsOf, "effectiveAsOf");
  if (effectiveAsOf > requestedAsOf) invalid("effectiveAsOf 晚于 requestedAsOf");

  if (!Array.isArray(data.bars) || data.bars.length < 1 || data.bars.length > 500) {
    invalid("日线窗口必须包含 1 到 500 根记录");
  }
  if (!Number.isInteger(data.barCount) || data.barCount !== data.bars.length) {
    invalid("barCount 与返回记录数不一致");
  }
  if (
    !Array.isArray(data.sourceVersions) ||
    !Array.from(data.sourceVersions).every(isNonEmptyText)
  ) {
    invalid("缺少有效的 sourceVersions 溯源");
  }
  if (!Array.isArray(data.evidenceIds) || !Array.from(data.evidenceIds).every(isNonEmptyText)) {
    invalid("缺少有效的 evidenceIds 溯源");
  }
  if (data.sourceVersions.length === 0 || data.evidenceIds.length === 0) {
    invalid("缺少来源版本或证据标识");
  }
  if (
    data.freshnessSeconds !== null &&
    (!Number.isFinite(data.freshnessSeconds) || data.freshnessSeconds < 0)
  ) {
    invalid("freshnessSeconds 必须是非负有限数值或 null");
  }

  const declaredSources = new Set(data.sourceVersions);
  const declaredEvidence = new Set(data.evidenceIds);
  const observedSources = new Set<string>();
  const observedEvidence = new Set<string>();
  let previousDate: string | null = null;
  for (const [index, bar] of data.bars.entries()) {
    validateBar(bar, effectiveAsOf, index);
    const sourceVersion = `${bar.source}@${bar.sourceVersion}`;
    if (!declaredSources.has(sourceVersion) || !declaredEvidence.has(bar.evidenceId)) {
      invalid(`第 ${index + 1} 根日线溯源与响应清单不一致`);
    }
    observedSources.add(sourceVersion);
    observedEvidence.add(bar.evidenceId);
    if (previousDate !== null && bar.date <= previousDate)
      invalid("日线日期必须严格升序且不能重复");
    previousDate = bar.date;
  }
  if (
    observedSources.size !== declaredSources.size ||
    observedEvidence.size !== declaredEvidence.size
  ) {
    invalid("日线溯源与响应清单不一致");
  }

  const finalBar = data.bars.at(-1);
  if (finalBar === undefined) invalid("日线窗口为空");
  if (data.dataCutoffTime !== finalBar.eventTime)
    invalid("dataCutoffTime 必须等于末根日线 eventTime");
  requireTimestamp(data.dataCutoffTime, "dataCutoffTime");
}

function normalizedTimestampForFilename(value: string): string {
  const match = RFC3339_PATTERN.exec(value);
  if (match === null) return invalid("effectiveAsOf 无法规范化");

  const zone = match[6]!;
  const offsetHour = zone === "Z" ? 0 : Number(zone.slice(1, 3));
  const offsetMinute = zone === "Z" ? 0 : Number(zone.slice(4, 6));
  const offsetMillis =
    (zone === "Z" ? 0 : (zone[0] === "+" ? 1 : -1) * (offsetHour * 60 + offsetMinute)) * 60_000;
  const utcMillis =
    Date.parse(`${match[1]}T${match[2]}:${match[3]}:${match[4]}.000Z`) - offsetMillis;
  const utcSecond = new Date(utcMillis).toISOString().slice(0, 19);
  const fractional = (match[5] ?? "").replace(/0+$/, "");
  return `${utcSecond.replace(/[-:]/g, "")}${fractional}Z`;
}

function csvCell(value: string): string {
  const safeValue = FORMULA_PREFIX_PATTERN.test(value) ? `'${value}` : value;
  return `"${safeValue.replaceAll('"', '""')}"`;
}

function rowValues(data: InstrumentBarsResponse, bar: InstrumentDailyBar): string[] {
  return [
    data.instrumentId,
    data.mode,
    data.requestedAsOf,
    data.effectiveAsOf,
    data.dataCutoffTime!,
    data.interval,
    data.priceType,
    String(data.barCount),
    data.schemaVersion,
    data.dataMeaning,
    data.status,
    data.freshnessSeconds === null ? "null" : String(data.freshnessSeconds),
    bar.date,
    bar.eventTime,
    bar.open,
    bar.high,
    bar.low,
    bar.close,
    bar.volume,
    bar.amount,
    String(bar.suspended),
    bar.availableTime,
    bar.processingTime,
    bar.source,
    bar.sourceVersion,
    bar.dataVersion,
    bar.evidenceId,
  ];
}

/** Serialize the returned daily RAW window without changing its order or decimal precision. */
export function prepareInstrumentBarsCsv(data: InstrumentBarsResponse): {
  filename: string;
  csv: string;
  barCount: number;
} {
  validateResponse(data);

  const filename = `${data.instrumentId}-daily-raw-${normalizedTimestampForFilename(data.effectiveAsOf)}-${data.barCount}.csv`;
  const rows = [
    CSV_COLUMNS.map(csvCell).join(","),
    ...data.bars.map((bar) => rowValues(data, bar).map(csvCell).join(",")),
  ];

  return {
    filename,
    csv: `\uFEFF${rows.join("\r\n")}\r\n`,
    barCount: data.barCount,
  };
}
