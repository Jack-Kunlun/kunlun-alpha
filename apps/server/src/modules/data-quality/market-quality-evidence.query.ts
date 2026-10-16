import type {
  MarketQualityEvidencePage,
  MarketQualitySource,
  MarketQualityStatus,
} from "@kunlun/shared-types";

const SOURCE_VALUES: readonly MarketQualitySource[] = [
  "tushare-pro",
  "akshare-tencent",
  "akshare-sina",
  "akshare-eastmoney",
];
const STATUS_VALUES: readonly MarketQualityStatus[] = ["REJECTED", "FILTERED"];
const SOURCE_SET = new Set<string>(SOURCE_VALUES);
const STATUS_SET = new Set<string>(STATUS_VALUES);
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const UNIFIED_CODE_PATTERN = /^\d{6}\.(SH|SZ|BJ)$/;
const SNAPSHOT_ID_PATTERN = /^[0-9a-f]{64}$/;
const ALLOWED_KEYS = new Set([
  "source",
  "unifiedCode",
  "status",
  "start",
  "end",
  "snapshotId",
  "limit",
  "offset",
]);
const DAY_MS = 24 * 60 * 60 * 1000;
export const MARKET_QUALITY_EVIDENCE_DEFAULT_LIMIT = 20;
export const MARKET_QUALITY_EVIDENCE_MAX_LIMIT = 100;
export const MARKET_QUALITY_EVIDENCE_MAX_OFFSET = 10_000;
export const MARKET_QUALITY_EVIDENCE_MAX_WINDOW_DAYS = 366;

export class MarketQualityEvidenceValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MarketQualityEvidenceValidationError";
  }
}

export interface MarketQualityEvidenceQuery {
  source?: MarketQualitySource;
  unifiedCode?: string;
  status?: MarketQualityStatus;
  start?: string;
  end?: string;
  snapshotId?: string;
  limit: number;
  offset: number;
}

export interface MarketQualityEvidenceDetailQuery {
  snapshotId: string;
}

function asObject(input: unknown): Record<string, unknown> {
  if (typeof input !== "object" || input === null || Array.isArray(input)) {
    throw new MarketQualityEvidenceValidationError("query must be an object");
  }
  return input as Record<string, unknown>;
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== "string" || value.trim() === "") {
    throw new MarketQualityEvidenceValidationError(`${field} must be a non-empty string`);
  }
  return value;
}

function isLegalDate(value: string): boolean {
  if (!DATE_PATTERN.test(value)) return false;
  const [yearText, monthText, dayText] = value.split("-");
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const date = new Date(Date.UTC(year, month - 1, day));
  return (
    date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
  );
}

function date(value: unknown, field: string): string {
  const text = requiredString(value, field);
  if (!isLegalDate(text)) {
    throw new MarketQualityEvidenceValidationError(`${field} must be a valid YYYY-MM-DD date`);
  }
  return text;
}

function boundedInteger(value: unknown, field: string, minimum: number, maximum: number): number {
  const parsed =
    typeof value === "number"
      ? value
      : typeof value === "string" && /^(0|[1-9][0-9]*)$/.test(value)
        ? Number(value)
        : Number.NaN;
  if (!Number.isSafeInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new MarketQualityEvidenceValidationError(
      `${field} must be an integer between ${minimum} and ${maximum}`,
    );
  }
  return parsed;
}

function validateSnapshotId(value: unknown, field = "snapshotId"): string {
  const text = requiredString(value, field);
  if (!SNAPSHOT_ID_PATTERN.test(text)) {
    throw new MarketQualityEvidenceValidationError(`${field} must be a lowercase SHA-256 id`);
  }
  return text;
}

export function validateMarketQualityEvidenceId(value: unknown): string {
  const text = requiredString(value, "opaqueId");
  if (!/^mqe-[0-9a-f]{64}$/.test(text)) {
    throw new MarketQualityEvidenceValidationError("opaqueId is invalid");
  }
  return text;
}

export function parseMarketQualityEvidenceQuery(input: unknown): MarketQualityEvidenceQuery {
  const record = asObject(input);
  for (const key of Object.keys(record)) {
    if (!ALLOWED_KEYS.has(key)) {
      throw new MarketQualityEvidenceValidationError("unsupported market evidence query parameter");
    }
  }

  const query: MarketQualityEvidenceQuery = {
    limit:
      record.limit === undefined
        ? MARKET_QUALITY_EVIDENCE_DEFAULT_LIMIT
        : boundedInteger(record.limit, "limit", 1, MARKET_QUALITY_EVIDENCE_MAX_LIMIT),
    offset:
      record.offset === undefined
        ? 0
        : boundedInteger(record.offset, "offset", 0, MARKET_QUALITY_EVIDENCE_MAX_OFFSET),
  };
  if (record.source !== undefined) {
    const source = requiredString(record.source, "source");
    if (!SOURCE_SET.has(source)) {
      throw new MarketQualityEvidenceValidationError("source is not supported");
    }
    query.source = source as MarketQualitySource;
  }
  if (record.unifiedCode !== undefined) {
    const unifiedCode = requiredString(record.unifiedCode, "unifiedCode");
    if (!UNIFIED_CODE_PATTERN.test(unifiedCode)) {
      throw new MarketQualityEvidenceValidationError(
        "unifiedCode must use suffix form like 600519.SH",
      );
    }
    query.unifiedCode = unifiedCode;
  }
  if (record.status !== undefined) {
    const status = requiredString(record.status, "status");
    if (!STATUS_SET.has(status)) {
      throw new MarketQualityEvidenceValidationError("status is not supported");
    }
    query.status = status as MarketQualityStatus;
  }
  const hasStart = record.start !== undefined;
  const hasEnd = record.end !== undefined;
  if (hasStart !== hasEnd) {
    throw new MarketQualityEvidenceValidationError("start and end must be provided together");
  }
  if (hasStart && hasEnd) {
    query.start = date(record.start, "start");
    query.end = date(record.end, "end");
    if (query.start > query.end) {
      throw new MarketQualityEvidenceValidationError("start must not be after end");
    }
    const days =
      (Date.parse(`${query.end}T00:00:00.000Z`) - Date.parse(`${query.start}T00:00:00.000Z`)) /
        DAY_MS +
      1;
    if (days > MARKET_QUALITY_EVIDENCE_MAX_WINDOW_DAYS) {
      throw new MarketQualityEvidenceValidationError(
        "market evidence date window must not exceed 366 calendar days",
      );
    }
  }
  if (record.snapshotId !== undefined) query.snapshotId = validateSnapshotId(record.snapshotId);
  if (query.offset > 0 && query.snapshotId === undefined) {
    throw new MarketQualityEvidenceValidationError("offset greater than zero requires snapshotId");
  }
  return query;
}

export function parseMarketQualityEvidenceDetailQuery(
  input: unknown,
): MarketQualityEvidenceDetailQuery {
  const record = asObject(input);
  const keys = Object.keys(record);
  if (keys.length !== 1 || keys[0] !== "snapshotId") {
    throw new MarketQualityEvidenceValidationError(
      "snapshotId is required for market evidence detail",
    );
  }
  return { snapshotId: validateSnapshotId(record.snapshotId) };
}

export function matchesMarketQualityEvidenceDateWindow(
  record: Pick<MarketQualityEvidencePage["records"][number], "requestedStart" | "requestedEnd">,
  query: Pick<MarketQualityEvidenceQuery, "start" | "end">,
): boolean {
  if (query.start === undefined || query.end === undefined) return true;
  return record.requestedStart <= query.end && record.requestedEnd >= query.start;
}
