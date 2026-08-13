/** Shared domain types. Generated from packages/contracts/schemas/. DO NOT EDIT BY HAND. */
/**
 * Service health-check response
 */
export interface HealthStatus {
  /**
   * Current health status
   */
  status: "ok" | "degraded" | "error";
  /**
   * ISO 8601 timestamp of the check
   */
  timestamp: string;
  /**
   * Service version string
   */
  version: string;
}

/**
 * Listing board classification for A-share securities
 */
export interface Board {
  /**
   * Board identifier: MAIN (主板), CHINEXT (创业板), STAR (科创板), BSE (北交所)
   */
  id: "MAIN" | "CHINEXT" | "STAR" | "BSE";
  /**
   * Board name in Chinese
   */
  name: string;
  /**
   * Exchange the board belongs to
   */
  exchange: "SH" | "SZ" | "BJ";
}

/**
 * Securities exchange identity used by the unified instrument code
 */
export interface Exchange {
  /**
   * Exchange code used in the unified instrument code (SH.600000)
   */
  code: "SH" | "SZ" | "BJ";
  /**
   * Full exchange name in Chinese
   */
  name: string;
  /**
   * Common Chinese short name
   */
  abbreviation: string;
  /**
   * ISO 10383 Market Identifier Code (XSHG / XSHE / XBES)
   */
  mic: string;
  /**
   * ISO 3166-1 alpha-2 country code
   */
  country: "CN";
  /**
   * Settlement currency of the exchange
   */
  currency: "CNY";
}

/**
 * Unified security master identity. The unifiedCode is the single domain key; external formats must be normalized before entering the domain layer
 */
export interface Instrument {
  /**
   * Unified domain key in the form {EXCHANGE}.{code}, e.g. SH.600000
   */
  unifiedCode: string;
  /**
   * Raw 6-digit exchange code
   */
  code: string;
  /**
   * Exchange code; must match the unifiedCode prefix
   */
  exchange: "SH" | "SZ" | "BJ";
  /**
   * Listing board
   */
  board: "MAIN" | "CHINEXT" | "STAR" | "BSE";
  /**
   * Security type: STOCK / ETF / LOF / FUND
   */
  type: "STOCK" | "ETF" | "LOF" | "FUND";
  /**
   * Security display name
   */
  name: string;
  /**
   * Trading status; ST and delisting are fields, not code changes
   */
  tradingStatus: "LISTED" | "SUSPENDED" | "ST" | "DELISTED";
  /**
   * Trading currency
   */
  currency: "CNY";
  /**
   * Optional first listing date (ISO 8601 date)
   */
  listDate?: string;
  /**
   * Optional delisting date (ISO 8601 date)
   */
  delistDate?: string;
}

/**
 * Trading status of an instrument. ST and delisting are statuses, never code changes
 */
export interface TradingStatus {
  /**
   * LISTED: 正常上市; SUSPENDED: 停牌; ST: 风险警示 (ST/*ST); DELISTED: 退市
   */
  value: "LISTED" | "SUSPENDED" | "ST" | "DELISTED";
  /**
   * Human-readable label in Chinese
   */
  label: string;
}
