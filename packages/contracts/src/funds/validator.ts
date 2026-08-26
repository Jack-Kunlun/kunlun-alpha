/**
 * Precious-metal fund validator.
 *
 * Classification is explicit: the fund asset class is always
 * `PRECIOUS_METALS`; GOLD/SILVER/OTHER identify the underlying commodity only.
 * Classification validity, source provenance and review confidence are kept
 * with each historical record. NAV/iNAV are separate reference contracts and
 * are never interpreted as executable prices here.
 */

export type AssetType = "ETF" | "LOF" | "FUND";
export type FundAssetClass = "PRECIOUS_METALS";
export type UnderlyingCommodity = "GOLD" | "SILVER" | "OTHER";
export type ReviewStatus = "UNREVIEWED" | "NEEDS_REVIEW" | "REVIEWED" | "REJECTED";

export interface RecurringFee {
  kind: string;
  rate: number;
  validFrom: string;
  validTo?: string | null;
  source: string;
}

export interface PreciousMetalFund {
  unifiedCode: string;
  exchange: "SH" | "SZ" | "BJ";
  assetType: AssetType;
  fundAssetClass: FundAssetClass;
  underlyingCommodity: UnderlyingCommodity;
  tradingCurrency: string;
  navCurrency: string;
  benchmarkOrTrackingIndex: string;
  benchmarkSeriesId?: string | null;
  managementFeeRate: number;
  validFrom: string;
  validTo?: string | null;
  source: string;
  eventTime?: string;
  publishTime: string;
  ingestTime: string;
  availableTime: string;
  processingTime: string;
  rawObjectId: string;
  confidence: number;
  reviewStatus: ReviewStatus;
  recurringFees?: RecurringFee[];
}

export interface BenchmarkSeriesPoint {
  schemaVersion: "benchmark-series-point-v1";
  benchmarkId: string;
  currency: string;
  priceBasis: string;
  referenceValue: string;
  eventTime: string;
  ingestTime: string;
  availableTime: string;
  processingTime: string;
  source: string;
  sourceRevision: string;
  rawObjectId: string;
  payloadDigest: string;
  referenceOnly: true;
}

export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

export interface FundValidationOptions {
  decisionTime?: string;
}

const ASSET_TYPES: readonly string[] = ["ETF", "LOF", "FUND"];
const COMMODITIES: readonly string[] = ["GOLD", "SILVER", "OTHER"];
const REVIEW_STATUSES: readonly string[] = ["UNREVIEWED", "NEEDS_REVIEW", "REVIEWED", "REJECTED"];
const BENCHMARK_SERIES_POINT_SCHEMA_VERSION = "benchmark-series-point-v1";
const UNIFIED_CODE_PATTERN = /^\d{6}\.(SH|SZ|BJ)$/;
const CURRENCY_PATTERN = /^[A-Z]{3}$/;
const CANONICAL_BENCHMARK_ID_PATTERN =
  /^benchmark:v1:[a-z0-9][a-z0-9._-]{0,31}:[a-z0-9][a-z0-9._-]{0,127}$/;
const CANONICAL_DECIMAL_PATTERN =
  /^(?:0\.[0-9]*[1-9][0-9]*|[1-9][0-9]*(?:\.[0-9]+)?)$/;
const BENCHMARK_ID_MAX_LENGTH = 174;
const PRICE_BASIS_MAX_LENGTH = 64;
const REFERENCE_VALUE_MAX_LENGTH = 64;
const PROVENANCE_STRING_MAX_LENGTH = 256;
const PAYLOAD_DIGEST_PATTERN = /^sha256:[0-9a-f]{64}$/;
const STRICT_RFC3339_PATTERN =
  /^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]{1,6}))?(Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$/;

type StrictRfc3339Instant = readonly [milliseconds: number, microseconds: number];

export function validatePreciousMetalFund(
  fund: PreciousMetalFund,
  options: FundValidationOptions = {},
): ValidationResult {
  const errors: string[] = [];

  if (!UNIFIED_CODE_PATTERN.test(fund.unifiedCode)) {
    errors.push("unifiedCode must use suffix form");
  } else if (fund.unifiedCode.slice(7) !== fund.exchange) {
    errors.push("exchange must match unifiedCode suffix");
  }
  if (!ASSET_TYPES.includes(fund.assetType)) {
    errors.push("assetType must be ETF/LOF/FUND");
  }
  if (fund.fundAssetClass !== "PRECIOUS_METALS") {
    errors.push("fundAssetClass must be PRECIOUS_METALS");
  }
  if (!COMMODITIES.includes(fund.underlyingCommodity)) {
    errors.push("underlyingCommodity must be GOLD/SILVER/OTHER");
  }
  if (fund.tradingCurrency !== "CNY") {
    errors.push("tradingCurrency must be CNY");
  }
  if (!CURRENCY_PATTERN.test(fund.navCurrency)) {
    errors.push("navCurrency must be an ISO 4217 currency code");
  }
  if (fund.benchmarkOrTrackingIndex.trim() === "") {
    errors.push("benchmarkOrTrackingIndex must be non-empty");
  }
  if (fund.benchmarkSeriesId !== undefined && fund.benchmarkSeriesId !== null) {
    if (!isCanonicalBenchmarkId(fund.benchmarkSeriesId)) {
      errors.push("benchmarkSeriesId must use canonical benchmark:v1 identity");
    }
  }
  if (!Number.isFinite(fund.managementFeeRate) || fund.managementFeeRate < 0) {
    errors.push("managementFeeRate must be >= 0");
  } else if (fund.managementFeeRate > 1) {
    errors.push("managementFeeRate must be <= 1");
  }
  if (!isIsoDate(fund.validFrom)) {
    errors.push("validFrom must be an ISO date");
  }
  if (fund.validTo !== undefined && fund.validTo !== null && !isIsoDate(fund.validTo)) {
    errors.push("validTo must be an ISO date or null");
  }
  if (fund.validTo !== undefined && fund.validTo !== null && fund.validFrom > fund.validTo) {
    errors.push("validFrom must be <= validTo");
  }
  if (fund.source.trim() === "") {
    errors.push("source must be non-empty");
  }
  if (fund.rawObjectId.trim() === "") {
    errors.push("rawObjectId must be non-empty");
  }
  if (!Number.isFinite(fund.confidence) || fund.confidence < 0 || fund.confidence > 1) {
    errors.push("confidence must be between 0 and 1");
  }
  if (!REVIEW_STATUSES.includes(fund.reviewStatus)) {
    errors.push("reviewStatus is invalid");
  }

  const timestampEntries: Array<[string, string]> = [
    ["publishTime", fund.publishTime],
    ["ingestTime", fund.ingestTime],
    ["availableTime", fund.availableTime],
    ["processingTime", fund.processingTime],
  ];
  if (fund.eventTime !== undefined) timestampEntries.unshift(["eventTime", fund.eventTime]);
  const timestampValues = timestampEntries.map(([name, value]) => {
    if (!isTimezoneAwareDateTime(value)) errors.push(`${name} must be timezone-aware`);
    return Date.parse(value);
  });
  if (timestampValues.every((value) => Number.isFinite(value))) {
    for (let index = 1; index < timestampValues.length; index += 1) {
      const previous = timestampValues[index - 1];
      const current = timestampValues[index];
      if (previous !== undefined && current !== undefined && previous > current) {
        errors.push("event/publish/ingest/available/processing order invalid");
        break;
      }
    }
  }
  if (options.decisionTime !== undefined) {
    if (!isTimezoneAwareDateTime(options.decisionTime)) {
      errors.push("decisionTime must be timezone-aware");
    } else if (
      isTimezoneAwareDateTime(fund.availableTime) &&
      Date.parse(fund.availableTime) > Date.parse(options.decisionTime)
    ) {
      errors.push("availableTime must not be later than decisionTime");
    }
  }

  for (const fee of fund.recurringFees ?? []) {
    if (fee.kind.trim() === "") errors.push("recurring fee kind must be non-empty");
    if (!Number.isFinite(fee.rate) || fee.rate < 0 || fee.rate > 1) {
      errors.push("recurring fee rate must be between 0 and 1");
    }
    if (!isIsoDate(fee.validFrom)) errors.push("recurring fee validFrom must be an ISO date");
    if (fee.validTo !== undefined && fee.validTo !== null && !isIsoDate(fee.validTo)) {
      errors.push("recurring fee validTo must be an ISO date or null");
    }
    if (fee.validTo !== undefined && fee.validTo !== null && fee.validFrom > fee.validTo) {
      errors.push("recurring fee validFrom must be <= validTo");
    }
    if (fee.source.trim() === "") errors.push("recurring fee source must be non-empty");
  }

  return { valid: errors.length === 0, errors };
}

export function validateBenchmarkSeriesPoint(point: BenchmarkSeriesPoint): ValidationResult {
  const errors: string[] = [];

  if (point.schemaVersion !== BENCHMARK_SERIES_POINT_SCHEMA_VERSION) {
    errors.push("schemaVersion must be benchmark-series-point-v1");
  }
  if (!isCanonicalBenchmarkId(point.benchmarkId)) {
    errors.push("benchmarkId must use canonical benchmark:v1 identity");
  }
  if (typeof point.currency !== "string" || !CURRENCY_PATTERN.test(point.currency)) {
    errors.push("currency must be an ISO 4217 currency code");
  }
  if (!isNonEmptyBoundedString(point.priceBasis, PRICE_BASIS_MAX_LENGTH)) {
    errors.push("priceBasis must be non-empty and no longer than 64 characters");
  }
  if (!isCanonicalDecimal(point.referenceValue)) {
    errors.push("referenceValue must be a canonical positive fixed-point decimal string");
  }
  if (point.referenceOnly !== true) errors.push("referenceOnly must be true");
  if (!isNonEmptyBoundedString(point.source, PROVENANCE_STRING_MAX_LENGTH)) {
    errors.push("source must be non-empty and no longer than 256 characters");
  }
  if (!isNonEmptyBoundedString(point.sourceRevision, PROVENANCE_STRING_MAX_LENGTH)) {
    errors.push("sourceRevision must be non-empty and no longer than 256 characters");
  }
  if (!isNonEmptyBoundedString(point.rawObjectId, PROVENANCE_STRING_MAX_LENGTH)) {
    errors.push("rawObjectId must be non-empty and no longer than 256 characters");
  }
  if (typeof point.payloadDigest !== "string" || !PAYLOAD_DIGEST_PATTERN.test(point.payloadDigest)) {
    errors.push("payloadDigest must be a sha256 digest");
  }

  const timestampEntries: Array<[string, unknown]> = [
    ["eventTime", point.eventTime],
    ["ingestTime", point.ingestTime],
    ["availableTime", point.availableTime],
    ["processingTime", point.processingTime],
  ];
  const timestampValues = timestampEntries.map(([name, value]) => {
    const parsed = parseStrictRfc3339(value);
    if (parsed === null) errors.push(`${name} must be a strict RFC3339 timestamp`);
    return parsed;
  });
  if (timestampValues.every((value): value is StrictRfc3339Instant => value !== null)) {
    for (let index = 1; index < timestampValues.length; index += 1) {
      const previous = timestampValues[index - 1];
      const current = timestampValues[index];
      if (previous !== undefined && current !== undefined && compareInstants(previous, current) > 0) {
        errors.push("event/ingest/available/processing order invalid");
        break;
      }
    }
  }

  return { valid: errors.length === 0, errors };
}

export function benchmarkSeriesMatches(
  fund: PreciousMetalFund,
  point: BenchmarkSeriesPoint,
): boolean {
  if (!isCanonicalBenchmarkId(fund.benchmarkSeriesId)) return false;
  if (!isCanonicalBenchmarkId(point.benchmarkId)) return false;
  try {
    if (!validatePreciousMetalFund(fund).valid) return false;
    if (!validateBenchmarkSeriesPoint(point).valid) return false;
  } catch {
    return false;
  }
  return fund.benchmarkSeriesId === point.benchmarkId;
}

function isIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().startsWith(value);
}

function isTimezoneAwareDateTime(value: string): boolean {
  return /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
}

function isCanonicalBenchmarkId(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length <= BENCHMARK_ID_MAX_LENGTH &&
    CANONICAL_BENCHMARK_ID_PATTERN.test(value)
  );
}

function isCanonicalDecimal(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length <= REFERENCE_VALUE_MAX_LENGTH &&
    CANONICAL_DECIMAL_PATTERN.test(value)
  );
}

function isNonEmptyBoundedString(value: unknown, maxLength: number): value is string {
  return (
    typeof value === "string" &&
    value.length >= 1 &&
    value.length <= maxLength &&
    value.trim() !== ""
  );
}

function parseStrictRfc3339(value: unknown): StrictRfc3339Instant | null {
  if (typeof value !== "string") return null;
  const match = STRICT_RFC3339_PATTERN.exec(value);
  if (match === null) return null;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const monthLengths = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (
    year === 0 ||
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > (monthLengths[month - 1] ?? 0) ||
    hour > 23 ||
    minute > 59 ||
    second > 59
  ) {
    return null;
  }

  const baseValue = value.replace(/\.[0-9]{1,6}(?=Z|[+-])/, "");
  const milliseconds = Date.parse(baseValue);
  if (!Number.isFinite(milliseconds)) return null;
  const microseconds = Number((match[7] ?? "").padEnd(6, "0"));
  return [milliseconds, microseconds];
}

function compareInstants(left: StrictRfc3339Instant, right: StrictRfc3339Instant): number {
  if (left[0] !== right[0]) return left[0] < right[0] ? -1 : 1;
  if (left[1] === right[1]) return 0;
  return left[1] < right[1] ? -1 : 1;
}
