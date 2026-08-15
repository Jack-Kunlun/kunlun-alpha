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

export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

export interface FundValidationOptions {
  decisionTime?: string;
}

const ASSET_TYPES: readonly string[] = ["ETF", "LOF", "FUND"];
const COMMODITIES: readonly string[] = ["GOLD", "SILVER", "OTHER"];
const REVIEW_STATUSES: readonly string[] = [
  "UNREVIEWED",
  "NEEDS_REVIEW",
  "REVIEWED",
  "REJECTED",
];
const UNIFIED_CODE_PATTERN = /^\d{6}\.(SH|SZ|BJ)$/;
const CURRENCY_PATTERN = /^[A-Z]{3}$/;

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

function isIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().startsWith(value);
}

function isTimezoneAwareDateTime(value: string): boolean {
  return /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
}
