import type {
  MarketQualityEvidenceDetail,
  MarketQualityEvent,
  MarketQualityEvidencePage,
  MarketQualityEvidenceRecord,
  MarketQualityFilteredRecord,
} from "@kunlun/shared-types";

const SNAPSHOT_ID = /^[0-9a-f]{64}$/;
const EVIDENCE_ID = /^mqe-[0-9a-f]{64}$/;
const CODE = /^\d{6}\.(SH|SZ|BJ)$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const RFC3339 = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$/;
const SOURCES = ["tushare-pro", "akshare-tencent", "akshare-sina", "akshare-eastmoney"] as const;
const INTERVALS = ["DAILY", "MINUTE_1", "MINUTE_5"] as const;
const STATUSES = ["REJECTED", "FILTERED"] as const;
const REASONS = [
  "PROVIDER_PARSE_ERROR",
  "BAR_QUALITY_REJECTED",
  "SINA_OVERFETCH_OUTSIDE_REQUEST",
] as const;
const KINDS = [
  "OUT_OF_ORDER",
  "DUPLICATE",
  "NEGATIVE_PRICE",
  "ABNORMAL_VOLUME",
  "MISSING_FIELD",
] as const;
const MAX_TEXT = 256;

export class MarketQualityEvidenceResponseError extends Error {
  constructor() {
    super("行情质量证据响应格式无效");
    this.name = "MarketQualityEvidenceResponseError";
  }
}

function invalid(): never {
  throw new MarketQualityEvidenceResponseError();
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

function text(value: unknown): string {
  if (typeof value !== "string" || value.length === 0 || value.length > MAX_TEXT) invalid();
  return value;
}

function oneOf<T extends string>(value: unknown, values: readonly T[]): T {
  const candidate = text(value);
  if (!values.includes(candidate as T)) invalid();
  return candidate as T;
}

function legalDate(value: unknown): string {
  const candidate = text(value);
  if (!DATE.test(candidate)) invalid();
  const [yearText, monthText, dayText] = candidate.split("-");
  const date = new Date(Date.UTC(Number(yearText), Number(monthText) - 1, Number(dayText)));
  if (
    date.getUTCFullYear() !== Number(yearText) ||
    date.getUTCMonth() !== Number(monthText) - 1 ||
    date.getUTCDate() !== Number(dayText)
  ) {
    invalid();
  }
  return candidate;
}

function instant(value: unknown): string {
  const candidate = text(value);
  parseInstant(candidate);
  return candidate;
}

function parseInstant(value: string): bigint {
  const match = RFC3339.exec(value);
  if (match === null) invalid();
  const [yearText, monthText, dayText] = match[1]!.split("-");
  const offset = match[6]!;
  if (
    Number(match[2]) > 23 ||
    Number(match[3]) > 59 ||
    Number(match[4]) > 59 ||
    !DATE.test(match[1]!) ||
    !Number.isFinite(Date.parse(`${match[1]}T${match[2]}:${match[3]}:${match[4]}.000${offset}`))
  ) {
    invalid();
  }
  const date = new Date(Date.UTC(Number(yearText), Number(monthText) - 1, Number(dayText)));
  if (
    date.getUTCFullYear() !== Number(yearText) ||
    date.getUTCMonth() !== Number(monthText) - 1 ||
    date.getUTCDate() !== Number(dayText)
  ) {
    invalid();
  }
  if (offset !== "Z" && (Number(offset.slice(1, 3)) > 23 || Number(offset.slice(4, 6)) > 59)) {
    invalid();
  }
  const milliseconds = Date.parse(`${match[1]}T${match[2]}:${match[3]}:${match[4]}.000${offset}`);
  if (!Number.isFinite(milliseconds)) invalid();
  return BigInt(milliseconds) * 1_000_000n + BigInt((match[5] ?? "").padEnd(9, "0"));
}

function shanghaiDate(value: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(Number(parseInstant(value) / 1_000_000n)));
  const values = new Map(parts.map((part) => [part.type, part.value]));
  const year = values.get("year");
  const month = values.get("month");
  const day = values.get("day");
  if (year === undefined || month === undefined || day === undefined) invalid();
  return `${year}-${month}-${day}`;
}

function count(value: unknown): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0 || (value as number) > 10_000) {
    invalid();
  }
  return value as number;
}

function parseEvent(value: unknown, code: string): MarketQualityEvent {
  const input = exact(value, ["kind", "unifiedCode", "timestamp"]);
  const unifiedCode = input.unifiedCode === null ? null : text(input.unifiedCode);
  if (unifiedCode !== null && (!CODE.test(unifiedCode) || unifiedCode !== code)) invalid();
  const timestamp = input.timestamp === null ? null : instant(input.timestamp);
  return {
    kind: oneOf(input.kind, KINDS),
    unifiedCode,
    timestamp,
  };
}

function parseFilteredRecord(
  value: unknown,
  requestedStart: string,
  requestedEnd: string,
): MarketQualityFilteredRecord {
  const input = exact(value, [
    "rawRowIndex",
    "timestamp",
    "requestedStart",
    "requestedEnd",
    "reasonCode",
  ]);
  if (!Number.isSafeInteger(input.rawRowIndex) || (input.rawRowIndex as number) < 0) invalid();
  const start = legalDate(input.requestedStart);
  const end = legalDate(input.requestedEnd);
  if (start !== requestedStart || end !== requestedEnd || start > end) invalid();
  if (input.reasonCode !== "SINA_OVERFETCH_OUTSIDE_REQUEST") invalid();
  const timestamp = instant(input.timestamp);
  const localDate = shanghaiDate(timestamp);
  if (localDate >= start && localDate <= end) invalid();
  return {
    rawRowIndex: input.rawRowIndex as number,
    timestamp,
    requestedStart: start,
    requestedEnd: end,
    reasonCode: "SINA_OVERFETCH_OUTSIDE_REQUEST",
  };
}

function parseRecord(value: unknown, publishedNanos: bigint): MarketQualityEvidenceRecord {
  const input = exact(value, [
    "evidenceId",
    "source",
    "unifiedCode",
    "interval",
    "requestedStart",
    "requestedEnd",
    "status",
    "reasonCode",
    "captureAvailableAt",
    "qualityRecordedAt",
    "rejectedRecordCount",
    "qualityEventCount",
    "filteredRecordCount",
    "qualityEvents",
    "filteredRecords",
  ]);
  const evidenceId = text(input.evidenceId);
  const unifiedCode = text(input.unifiedCode);
  const requestedStart = legalDate(input.requestedStart);
  const requestedEnd = legalDate(input.requestedEnd);
  const status = oneOf(input.status, STATUSES);
  const reasonCode = oneOf(input.reasonCode, REASONS);
  if (
    !EVIDENCE_ID.test(evidenceId) ||
    !CODE.test(unifiedCode) ||
    requestedStart > requestedEnd ||
    (status === "FILTERED" && reasonCode !== "SINA_OVERFETCH_OUTSIDE_REQUEST") ||
    (status === "REJECTED" && reasonCode === "SINA_OVERFETCH_OUTSIDE_REQUEST")
  ) {
    invalid();
  }
  if (
    status === "FILTERED" &&
    (input.source !== "akshare-sina" ||
      input.rejectedRecordCount !== 0 ||
      input.qualityEventCount !== 0)
  ) {
    invalid();
  }
  const qualityEvents = input.qualityEvents;
  const filteredRecords = input.filteredRecords;
  if (!Array.isArray(qualityEvents) || !Array.isArray(filteredRecords)) invalid();
  const parsedQualityEvents = qualityEvents.map((event) => parseEvent(event, unifiedCode));
  const parsedFilteredRecords = filteredRecords.map((record) =>
    parseFilteredRecord(record, requestedStart, requestedEnd),
  );
  const qualityEventCount = count(input.qualityEventCount);
  const filteredRecordCount = count(input.filteredRecordCount);
  const rejectedRecordCount = count(input.rejectedRecordCount);
  if (
    qualityEventCount !== parsedQualityEvents.length ||
    filteredRecordCount !== parsedFilteredRecords.length ||
    (status === "FILTERED" && (filteredRecordCount === 0 || rejectedRecordCount !== 0)) ||
    (status === "FILTERED" && qualityEventCount !== 0) ||
    (status === "REJECTED" && filteredRecordCount !== 0 && reasonCode !== "BAR_QUALITY_REJECTED") ||
    ((status === "FILTERED" || filteredRecordCount !== 0) && input.source !== "akshare-sina")
  ) {
    invalid();
  }
  const rawRowIndexes = new Set<number>();
  for (const filteredRecord of parsedFilteredRecords) {
    if (rawRowIndexes.has(filteredRecord.rawRowIndex)) invalid();
    rawRowIndexes.add(filteredRecord.rawRowIndex);
  }
  const captureAvailableAt = instant(input.captureAvailableAt);
  const qualityRecordedAt = instant(input.qualityRecordedAt);
  if (
    parseInstant(captureAvailableAt) > parseInstant(qualityRecordedAt) ||
    parseInstant(qualityRecordedAt) > publishedNanos
  ) {
    invalid();
  }
  return {
    evidenceId,
    source: oneOf(input.source, SOURCES),
    unifiedCode,
    interval: oneOf(input.interval, INTERVALS),
    requestedStart,
    requestedEnd,
    status,
    reasonCode,
    captureAvailableAt,
    qualityRecordedAt,
    rejectedRecordCount,
    qualityEventCount,
    filteredRecordCount,
    qualityEvents: parsedQualityEvents,
    filteredRecords: parsedFilteredRecords,
  };
}

export function parseMarketQualityEvidencePage(value: unknown): MarketQualityEvidencePage {
  const input = exact(value, [
    "schemaVersion",
    "snapshotId",
    "publishedAt",
    "snapshotRecordCount",
    "matchingRecordCount",
    "offset",
    "limit",
    "hasMore",
    "records",
  ]);
  if (
    input.schemaVersion !== "market-quality-evidence-v1" ||
    !SNAPSHOT_ID.test(text(input.snapshotId))
  )
    invalid();
  if (
    typeof input.hasMore !== "boolean" ||
    !Array.isArray(input.records) ||
    input.records.length > 100
  )
    invalid();
  const publishedAt = instant(input.publishedAt);
  const publishedNanos = parseInstant(publishedAt);
  const records = input.records.map((record) => parseRecord(record, publishedNanos));
  for (let index = 1; index < records.length; index += 1) {
    if (records[index - 1]!.evidenceId >= records[index]!.evidenceId) invalid();
  }
  const limit = typeof input.limit === "number" ? input.limit : Number.NaN;
  const result = {
    schemaVersion: "market-quality-evidence-v1" as const,
    snapshotId: input.snapshotId as string,
    publishedAt,
    snapshotRecordCount: count(input.snapshotRecordCount),
    matchingRecordCount: count(input.matchingRecordCount),
    offset: count(input.offset),
    limit,
    hasMore: input.hasMore,
    records,
  };
  if (
    !Number.isSafeInteger(limit) ||
    limit < 1 ||
    limit > 100 ||
    records.length > limit ||
    result.matchingRecordCount > result.snapshotRecordCount ||
    result.offset > 10_000 ||
    result.offset > result.matchingRecordCount ||
    result.hasMore !== result.offset + records.length < result.matchingRecordCount
  ) {
    invalid();
  }
  return result;
}

export function parseMarketQualityEvidenceDetail(value: unknown): MarketQualityEvidenceDetail {
  const input = exact(value, ["schemaVersion", "snapshotId", "publishedAt", "record"]);
  if (
    input.schemaVersion !== "market-quality-evidence-v1" ||
    !SNAPSHOT_ID.test(text(input.snapshotId))
  )
    invalid();
  const publishedAt = instant(input.publishedAt);
  return {
    schemaVersion: "market-quality-evidence-v1",
    snapshotId: input.snapshotId as string,
    publishedAt,
    record: parseRecord(input.record, parseInstant(publishedAt)),
  };
}
