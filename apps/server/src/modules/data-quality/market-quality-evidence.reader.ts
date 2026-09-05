import { createHash } from "node:crypto";
import { constants } from "node:fs";
import { lstat, open, realpath } from "node:fs/promises";
import { basename, dirname, join, parse, relative, resolve, sep } from "node:path";
import type {
  MarketQualityEvidenceRecord,
  MarketQualityEvidenceSnapshot,
  MarketQualityKind,
  MarketQualityReasonCode,
  MarketQualitySource,
  MarketQualityStatus,
} from "@kunlun/shared-types";

const CURRENT_SCHEMA_VERSION = "market-quality-current-v1" as const;
const SNAPSHOT_SCHEMA_VERSION = "market-quality-snapshot-v1" as const;
const HEX_64 = /^[0-9a-f]{64}$/;
const EVIDENCE_ID = /^mqe-[0-9a-f]{64}$/;
const CODE = /^\d{6}\.(SH|SZ|BJ)$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const RFC3339 =
  /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$/;
const MAX_BYTES = 8 * 1024 * 1024;
const MAX_POINTER_BYTES = 4096;
const MAX_RECORDS = 10_000;
const MAX_TEXT = 256;
const SOURCES: readonly MarketQualitySource[] = [
  "tushare-pro",
  "akshare-tencent",
  "akshare-sina",
  "akshare-eastmoney",
];
const STATUSES: readonly MarketQualityStatus[] = ["REJECTED", "FILTERED"];
const REASONS: readonly MarketQualityReasonCode[] = [
  "PROVIDER_PARSE_ERROR",
  "BAR_QUALITY_REJECTED",
  "SINA_OVERFETCH_OUTSIDE_REQUEST",
];
const KINDS: readonly MarketQualityKind[] = [
  "OUT_OF_ORDER",
  "DUPLICATE",
  "NEGATIVE_PRICE",
  "ABNORMAL_VOLUME",
  "MISSING_FIELD",
];

export class MarketQualityEvidenceReadError extends Error {
  constructor(message = "market quality evidence is unavailable") {
    super(message);
    this.name = "MarketQualityEvidenceReadError";
  }
}

export interface LoadedMarketQualityEvidenceSnapshot {
  snapshotId: string;
  snapshot: MarketQualityEvidenceSnapshot;
}

export interface MarketQualityEvidenceSnapshotReader {
  readCurrent(): Promise<LoadedMarketQualityEvidenceSnapshot>;
  readSnapshot(snapshotId: string): Promise<LoadedMarketQualityEvidenceSnapshot>;
}

function invalid(): never {
  throw new MarketQualityEvidenceReadError();
}

function object(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) invalid();
  return value as Record<string, unknown>;
}

function exactObject(value: unknown, fields: readonly string[]): Record<string, unknown> {
  const result = object(value);
  const expected = new Set(fields);
  const keys = Object.keys(result);
  if (keys.length !== fields.length || keys.some((key) => !expected.has(key))) invalid();
  return result;
}

function text(value: unknown, max = MAX_TEXT): string {
  if (typeof value !== "string" || value.length === 0 || value.length > max) invalid();
  return value;
}

function enumeration<T extends string>(value: unknown, values: readonly T[]): T {
  const candidate = text(value);
  if (!values.includes(candidate as T)) invalid();
  return candidate as T;
}

function integer(value: unknown, maximum = MAX_RECORDS): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0 || (value as number) > maximum) {
    invalid();
  }
  return value as number;
}

function safeNonNegativeInteger(value: unknown): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) invalid();
  return value as number;
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

function parseInstant(value: string): bigint {
  const match = RFC3339.exec(value);
  if (match === null) invalid();
  const datePart = match[1]!;
  const [yearText, monthText, dayText] = datePart.split("-");
  const hour = Number(match[2]);
  const minute = Number(match[3]);
  const second = Number(match[4]);
  if (
    !isLegalDateParts(Number(yearText), Number(monthText), Number(dayText)) ||
    hour > 23 ||
    minute > 59 ||
    second > 59
  ) {
    invalid();
  }
  const offset = match[6]!;
  if (offset !== "Z") {
    const offsetHour = Number(offset.slice(1, 3));
    const offsetMinute = Number(offset.slice(4, 6));
    if (offsetHour > 23 || offsetMinute > 59) invalid();
  }
  const base = `${datePart}T${match[2]}:${match[3]}:${match[4]}.000${offset}`;
  const milliseconds = Date.parse(base);
  if (Number.isNaN(milliseconds)) invalid();
  const fraction = (match[5] ?? "").padEnd(9, "0");
  return BigInt(milliseconds) * 1_000_000n + BigInt(fraction);
}

function instant(value: unknown): string {
  const candidate = text(value, 64);
  parseInstant(candidate);
  return candidate;
}

function isLegalDateParts(year: number, month: number, day: number): boolean {
  const date = new Date(Date.UTC(year, month - 1, day));
  return (
    date.getUTCFullYear() === year &&
    date.getUTCMonth() === month - 1 &&
    date.getUTCDate() === day
  );
}

function nullableInstant(value: unknown): string | null {
  return value === null ? null : instant(value);
}

function nullableCode(value: unknown, expected: string): string | null {
  if (value === null) return null;
  const candidate = text(value, 10);
  if (!CODE.test(candidate) || candidate !== expected) invalid();
  return candidate;
}

function validateEvent(value: unknown, expectedCode: string): MarketQualityEvidenceRecord["qualityEvents"][number] {
  const input = exactObject(value, ["kind", "unifiedCode", "timestamp"]);
  return {
    kind: enumeration(input.kind, KINDS),
    unifiedCode: nullableCode(input.unifiedCode, expectedCode),
    timestamp: nullableInstant(input.timestamp),
  };
}

function validateFilteredRecord(
  value: unknown,
  expectedStart: string,
  expectedEnd: string,
): MarketQualityEvidenceRecord["filteredRecords"][number] {
  const input = exactObject(value, [
    "rawRowIndex",
    "timestamp",
    "requestedStart",
    "requestedEnd",
    "reasonCode",
  ]);
  const requestedStart = legalDate(input.requestedStart);
  const requestedEnd = legalDate(input.requestedEnd);
  if (requestedStart !== expectedStart || requestedEnd !== expectedEnd) invalid();
  if (requestedStart > requestedEnd) invalid();
  if (input.reasonCode !== "SINA_OVERFETCH_OUTSIDE_REQUEST") invalid();
  const timestamp = instant(input.timestamp);
  const shanghaiDate = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(Number(parseInstant(timestamp) / 1_000_000n)));
  if (shanghaiDate >= requestedStart && shanghaiDate <= requestedEnd) invalid();
  return {
    rawRowIndex: safeNonNegativeInteger(input.rawRowIndex),
    timestamp,
    requestedStart,
    requestedEnd,
    reasonCode: "SINA_OVERFETCH_OUTSIDE_REQUEST",
  };
}

function validateRecord(value: unknown, now: bigint, publishedNanos: bigint): MarketQualityEvidenceRecord {
  const input = exactObject(value, [
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
  const evidenceId = text(input.evidenceId, 68);
  const unifiedCode = text(input.unifiedCode, 10);
  const requestedStart = legalDate(input.requestedStart);
  const requestedEnd = legalDate(input.requestedEnd);
  if (!EVIDENCE_ID.test(evidenceId) || !CODE.test(unifiedCode) || requestedStart > requestedEnd) {
    invalid();
  }
  const source = enumeration(input.source, SOURCES);
  const interval = enumeration(input.interval, ["DAILY", "MINUTE_1", "MINUTE_5"] as const);
  const status = enumeration(input.status, STATUSES);
  const reasonCode = enumeration(input.reasonCode, REASONS);
  if (
    (status === "FILTERED" && reasonCode !== "SINA_OVERFETCH_OUTSIDE_REQUEST") ||
    (status === "REJECTED" && reasonCode === "SINA_OVERFETCH_OUTSIDE_REQUEST") ||
    (status === "FILTERED" && source !== "akshare-sina")
  ) {
    invalid();
  }
  const captureAvailableAt = instant(input.captureAvailableAt);
  const qualityRecordedAt = instant(input.qualityRecordedAt);
  const captureNanos = parseInstant(captureAvailableAt);
  const qualityNanos = parseInstant(qualityRecordedAt);
  if (captureNanos > qualityNanos || qualityNanos > publishedNanos || publishedNanos > now) {
    invalid();
  }
  const qualityEvents = input.qualityEvents;
  const filteredRecords = input.filteredRecords;
  if (
    !Array.isArray(qualityEvents) ||
    !Array.isArray(filteredRecords) ||
    qualityEvents.length > MAX_RECORDS ||
    filteredRecords.length > MAX_RECORDS
  ) {
    invalid();
  }
  const parsedQualityEvents = qualityEvents.map((event) => validateEvent(event, unifiedCode));
  const parsedFilteredRecords = filteredRecords.map((record) =>
    validateFilteredRecord(record, requestedStart, requestedEnd),
  );
  const rejectedRecordCount = integer(input.rejectedRecordCount);
  const qualityEventCount = integer(input.qualityEventCount);
  const filteredRecordCount = integer(input.filteredRecordCount);
  if (
    qualityEventCount !== parsedQualityEvents.length ||
    filteredRecordCount !== parsedFilteredRecords.length ||
    (status === "FILTERED" &&
      (filteredRecordCount === 0 || rejectedRecordCount !== 0 || qualityEventCount !== 0)) ||
    (status === "REJECTED" &&
      filteredRecordCount !== 0 &&
      reasonCode !== "BAR_QUALITY_REJECTED") ||
    ((status === "FILTERED" || filteredRecordCount !== 0) && source !== "akshare-sina")
  ) {
    invalid();
  }
  const rawRowIndexes = new Set<number>();
  for (const filteredRecord of parsedFilteredRecords) {
    if (rawRowIndexes.has(filteredRecord.rawRowIndex)) invalid();
    rawRowIndexes.add(filteredRecord.rawRowIndex);
  }
  return {
    evidenceId,
    source,
    unifiedCode,
    interval,
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

function validateSnapshot(value: unknown, now: bigint): MarketQualityEvidenceSnapshot {
  const input = exactObject(value, ["schemaVersion", "publishedAt", "records"]);
  if (input.schemaVersion !== SNAPSHOT_SCHEMA_VERSION || !Array.isArray(input.records)) invalid();
  const publishedAt = instant(input.publishedAt);
  const publishedNanos = parseInstant(publishedAt);
  if (publishedNanos > now || input.records.length > MAX_RECORDS) invalid();
  const records = input.records.map((record) => validateRecord(record, now, publishedNanos));
  const evidenceIds = new Set<string>();
  for (let index = 0; index < records.length; index += 1) {
    const current = records[index]!;
    if (evidenceIds.has(current.evidenceId)) invalid();
    evidenceIds.add(current.evidenceId);
    if (index > 0 && records[index - 1]!.evidenceId >= current.evidenceId) invalid();
  }
  return { schemaVersion: SNAPSHOT_SCHEMA_VERSION, publishedAt, records };
}

async function readBoundedFile(filePath: string, maxBytes: number): Promise<Buffer> {
  let handle: Awaited<ReturnType<typeof open>> | undefined;
  try {
    const parent = dirname(filePath);
    const parentStat = await lstat(parent);
    if (!parentStat.isDirectory()) invalid();
    const parentRealpath = await realpath(parent);
    const fileStat = await lstat(filePath);
    if (!fileStat.isFile() || (await realpath(filePath)) !== join(parentRealpath, basename(filePath))) {
      invalid();
    }
    const noFollow = (constants as { O_NOFOLLOW?: number }).O_NOFOLLOW ?? 0;
    const nonBlocking = (constants as { O_NONBLOCK?: number }).O_NONBLOCK ?? 0;
    handle = await open(filePath, constants.O_RDONLY | noFollow | nonBlocking);
    const openedStat = await handle.stat();
    if (
      !openedStat.isFile() ||
      openedStat.size > maxBytes ||
      openedStat.dev !== fileStat.dev ||
      openedStat.ino !== fileStat.ino
    ) {
      invalid();
    }
    const bytes = Buffer.alloc(openedStat.size);
    let offset = 0;
    while (offset < bytes.length) {
      const result = await handle.read(bytes, offset, bytes.length - offset, offset);
      if (result.bytesRead === 0) invalid();
      offset += result.bytesRead;
    }
    const finalStat = await handle.stat();
    const finalParentStat = await lstat(parent);
    if (
      finalStat.size !== openedStat.size ||
      finalStat.dev !== openedStat.dev ||
      finalStat.ino !== openedStat.ino ||
      !finalParentStat.isDirectory() ||
      finalParentStat.dev !== parentStat.dev ||
      finalParentStat.ino !== parentStat.ino
    ) {
      invalid();
    }
    return bytes;
  } catch (error) {
    if (error instanceof MarketQualityEvidenceReadError) throw error;
    throw new MarketQualityEvidenceReadError();
  } finally {
    await handle?.close().catch(() => undefined);
  }
}

async function assertNoSymlinkComponents(path: string): Promise<void> {
  const absolute = resolve(path);
  const parsedRoot = parse(absolute).root;
  let current = parsedRoot;
  try {
    for (const component of relative(parsedRoot, absolute).split(sep).filter(Boolean)) {
      current = join(current, component);
      if ((await lstat(current)).isSymbolicLink()) invalid();
    }
  } catch (error) {
    if (error instanceof MarketQualityEvidenceReadError) throw error;
    throw new MarketQualityEvidenceReadError();
  }
}

function parseUtf8Json(bytes: Buffer): unknown {
  try {
    const textValue = bytes.toString("utf8");
    if (!Buffer.from(textValue, "utf8").equals(bytes)) invalid();
    return JSON.parse(textValue) as unknown;
  } catch (error) {
    if (error instanceof MarketQualityEvidenceReadError) throw error;
    throw new MarketQualityEvidenceReadError();
  }
}

export class FileMarketQualityEvidenceSnapshotReader implements MarketQualityEvidenceSnapshotReader {
  private readonly root: string;
  private readonly now: () => Date;

  constructor(root: string, now: () => Date = () => new Date()) {
    if (root.trim() === "") throw new MarketQualityEvidenceReadError();
    this.root = resolve(root);
    this.now = now;
  }

  async readCurrent(): Promise<LoadedMarketQualityEvidenceSnapshot> {
    await assertNoSymlinkComponents(this.root);
    const bytes = await readBoundedFile(join(this.root, "current.json"), MAX_POINTER_BYTES);
    const pointer = exactObject(parseUtf8Json(bytes), ["schemaVersion", "snapshotId"]);
    if (
      pointer.schemaVersion !== CURRENT_SCHEMA_VERSION ||
      typeof pointer.snapshotId !== "string" ||
      !HEX_64.test(pointer.snapshotId)
    ) {
      throw new MarketQualityEvidenceReadError();
    }
    return this.readSnapshot(pointer.snapshotId);
  }

  async readSnapshot(snapshotId: string): Promise<LoadedMarketQualityEvidenceSnapshot> {
    if (typeof snapshotId !== "string" || !HEX_64.test(snapshotId)) {
      throw new MarketQualityEvidenceReadError();
    }
    await assertNoSymlinkComponents(this.root);
    const filePath = join(this.root, "snapshots", `${snapshotId}.json`);
    const bytes = await readBoundedFile(filePath, MAX_BYTES);
    const actualDigest = createHash("sha256").update(bytes).digest("hex");
    if (actualDigest !== snapshotId) throw new MarketQualityEvidenceReadError();
    const nowDate = this.now();
    const now = nowDate.getTime();
    if (!Number.isFinite(now)) throw new MarketQualityEvidenceReadError();
    const snapshot = validateSnapshot(parseUtf8Json(bytes), BigInt(now) * 1_000_000n);
    return { snapshotId, snapshot };
  }
}

export class UnavailableMarketQualityEvidenceSnapshotReader
  implements MarketQualityEvidenceSnapshotReader
{
  async readCurrent(): Promise<LoadedMarketQualityEvidenceSnapshot> {
    throw new MarketQualityEvidenceReadError();
  }

  async readSnapshot(_snapshotId: string): Promise<LoadedMarketQualityEvidenceSnapshot> {
    throw new MarketQualityEvidenceReadError();
  }
}

export const MARKET_QUALITY_EVIDENCE_MAX_BYTES = MAX_BYTES;
export const MARKET_QUALITY_EVIDENCE_MAX_RECORDS = MAX_RECORDS;
export const MARKET_QUALITY_CURRENT_SCHEMA_VERSION = CURRENT_SCHEMA_VERSION;
