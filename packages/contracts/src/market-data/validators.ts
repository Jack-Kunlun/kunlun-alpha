/**
 * Market data validators.
 *
 * Pure validation functions for OHLCV bars, ticks, adjustment factors and
 * corporate actions. Rules: prices/volumes/amounts are non-negative; bar
 * high >= max(open, close, low) and low <= min(open, close, high) unless the
 * instrument was suspended (suspended bars must have zero volume/amount);
 * adjustment factors must be strictly positive. The precision rules in
 * packages/contracts/market-data/precision-rules.json are the single source
 * of truth shared with the Python port in market-core/models.
 */

export type ExchangeId = "SH" | "SZ" | "BJ";
export type BarInterval = "DAILY" | "MINUTE_1" | "MINUTE_5";
export type SessionKind = "CONTINUOUS" | "OPEN_AUCTION" | "CLOSE_AUCTION";
export type PriceType = "RAW" | "FORWARD_ADJUSTED" | "BACKWARD_ADJUSTED";
export type TickDirection = "BUY" | "SELL" | "NEUTRAL";
export type TradeType = "MATCH" | "AUCTION" | "BLOCK";
export type FactorType = "FORWARD" | "BACKWARD";
export type ActionType = "DIVIDEND" | "STOCK_DIVIDEND" | "SPLIT" | "RIGHTS_ISSUE";

export interface Bar {
  unifiedCode: string;
  exchange: ExchangeId;
  date: string;
  interval: BarInterval;
  session: SessionKind;
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount: number;
  priceType: PriceType;
  suspended?: boolean;
}

export interface Tick {
  unifiedCode: string;
  exchange: ExchangeId;
  date: string;
  timestamp: string;
  price: number;
  volume: number;
  amount: number;
  direction: TickDirection;
  tradeType: TradeType;
}

export interface AdjustmentFactor {
  unifiedCode: string;
  exchange: ExchangeId;
  date: string;
  factor: number;
  factorType: FactorType;
  note?: string;
}

export interface CorporateAction {
  unifiedCode: string;
  exchange: ExchangeId;
  exDate: string;
  actionType: ActionType;
  description: string;
  perShareCash?: number;
  perShareStock?: number;
  ratio?: number;
}

export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

function ok(): ValidationResult {
  return { valid: true, errors: [] };
}

function fail(error: string): ValidationResult {
  return { valid: false, errors: [error] };
}

function isNonNegative(value: number): boolean {
  return Number.isFinite(value) && value >= 0;
}

/**
 * Validate an OHLCV bar. A suspended bar must have zero volume and amount and
 * skips the high/low relationship check (OHLCV are all zero). A non-suspended
 * bar must satisfy high >= max(open, close, low) and low <= min(open, close,
 * high). Research prices (FORWARD_ADJUSTED / BACKWARD_ADJUSTED) and trade
 * prices (RAW) are kept separate via the required priceType field.
 */
export function validateBar(bar: Bar): ValidationResult {
  if (!isNonNegative(bar.open)) return fail("open must be >= 0");
  if (!isNonNegative(bar.high)) return fail("high must be >= 0");
  if (!isNonNegative(bar.low)) return fail("low must be >= 0");
  if (!isNonNegative(bar.close)) return fail("close must be >= 0");
  if (!isNonNegative(bar.volume)) return fail("volume must be >= 0");
  if (!isNonNegative(bar.amount)) return fail("amount must be >= 0");

  if (bar.suspended) {
    if (bar.volume !== 0) return fail("suspended bar must have zero volume");
    if (bar.amount !== 0) return fail("suspended bar must have zero amount");
    return ok();
  }

  const highest = Math.max(bar.open, bar.close, bar.low);
  if (bar.high < highest) return fail("high must be >= max(open, close, low)");
  const lowest = Math.min(bar.open, bar.close, bar.high);
  if (bar.low > lowest) return fail("low must be <= min(open, close, high)");
  return ok();
}

/** Validate a single executed trade: price, volume and amount are non-negative. */
export function validateTick(tick: Tick): ValidationResult {
  if (!isNonNegative(tick.price)) return fail("price must be >= 0");
  if (!isNonNegative(tick.volume)) return fail("volume must be >= 0");
  if (!isNonNegative(tick.amount)) return fail("amount must be >= 0");
  return ok();
}

/** Validate an adjustment factor: factor must be strictly positive. */
export function validateAdjustmentFactor(factor: AdjustmentFactor): ValidationResult {
  if (!Number.isFinite(factor.factor) || factor.factor <= 0) {
    return fail("factor must be > 0");
  }
  return ok();
}

/**
 * Validate a corporate action. Optional per-share cash/stock and rights ratio
 * must be non-negative when present.
 */
export function validateCorporateAction(action: CorporateAction): ValidationResult {
  if (action.perShareCash !== undefined && action.perShareCash < 0) {
    return fail("perShareCash must be >= 0");
  }
  if (action.perShareStock !== undefined && action.perShareStock < 0) {
    return fail("perShareStock must be >= 0");
  }
  if (action.ratio !== undefined && action.ratio < 0) {
    return fail("ratio must be >= 0");
  }
  return ok();
}
