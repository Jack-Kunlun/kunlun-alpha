/**
 * Precious-metal fund validator.
 *
 * The underlying commodity is explicit — it is never guessed from the product
 * name, and no spot/futures semantics are introduced. Validation covers asset
 * class, currency consistency and historical validity windows.
 */

export type AssetClass = "GOLD" | "SILVER" | "OTHER";

export interface PreciousMetalFund {
  unifiedCode: string;
  exchange: string;
  fundAssetClass: string;
  underlyingCommodity: string;
  currency: string;
  benchmark: string;
  managementFeeRate: number;
  validFrom: string;
  validTo: string | null;
  source: string;
}

export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

const ASSET_CLASSES: readonly string[] = ["GOLD", "SILVER", "OTHER"];

export function validatePreciousMetalFund(fund: PreciousMetalFund): ValidationResult {
  const errors: string[] = [];

  if (!ASSET_CLASSES.includes(fund.fundAssetClass)) {
    errors.push("fundAssetClass must be GOLD/SILVER/OTHER");
  }
  if (!ASSET_CLASSES.includes(fund.underlyingCommodity)) {
    errors.push("underlyingCommodity must be GOLD/SILVER/OTHER");
  }
  if (fund.currency !== "CNY") {
    errors.push("currency must be CNY");
  }
  if (fund.validTo !== null && fund.validFrom > fund.validTo) {
    errors.push("validFrom must be <= validTo");
  }
  if (fund.managementFeeRate < 0) {
    errors.push("managementFeeRate must be >= 0");
  }

  return { valid: errors.length === 0, errors };
}
