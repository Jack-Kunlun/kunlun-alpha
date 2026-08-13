/** Shared domain types. Generated from packages/contracts/schemas/. DO NOT EDIT BY HAND. */
/**
 * A scheduled exchange closure: a public holiday or an ad-hoc (temporary) closure. Weekends are derived by the calendar code and never stored as holidays
 */
export interface Holiday {
  /**
   * ISO 8601 closure date in Asia/Shanghai, e.g. 2026-01-01
   */
  date: string;
  /**
   * Exchange the closure applies to
   */
  exchange: "SH" | "SZ" | "BJ";
  /**
   * PUBLIC_HOLIDAY / TEMPORARY_CLOSURE / SPECIAL
   */
  reason: "PUBLIC_HOLIDAY" | "TEMPORARY_CLOSURE" | "SPECIAL";
  /**
   * Optional free-text reason, e.g. 元旦 / 台风临时休市
   */
  note?: string;
}

/**
 * Per-date calendar entry for an exchange: whether it is a trading day and, when it is not, why. The sessions of a trading day are assembled from the exchange session template; this model stays a pure per-date status record
 */
export interface TradingDay {
  /**
   * ISO 8601 calendar date in Asia/Shanghai, e.g. 2026-08-13
   */
  date: string;
  /**
   * Exchange this day entry applies to
   */
  exchange: "SH" | "SZ" | "BJ";
  /**
   * Whether the exchange trades on this date; weekends and holidays never count as trading days
   */
  isTradingDay: boolean;
  /**
   * Optional reason when isTradingDay is false
   */
  reason?: "WEEKEND" | "PUBLIC_HOLIDAY" | "TEMPORARY_CLOSURE" | "SPECIAL";
  /**
   * Optional free-text note (e.g. holiday name or closure cause)
   */
  note?: string;
}

/**
 * A named time interval within a trading day; local clock HH:MM in Asia/Shanghai, start inclusive, end exclusive. A session crossing midnight belongs to the trading day on which it starts
 */
export interface TradingSession {
  /**
   * Stable machine id, e.g. open-auction / morning / afternoon
   */
  sessionId: string;
  /**
   * Session kind: CONTINUOUS / OPEN_AUCTION / CLOSE_AUCTION / BREAK / NIGHT
   */
  kind: "CONTINUOUS" | "OPEN_AUCTION" | "CLOSE_AUCTION" | "BREAK" | "NIGHT";
  /**
   * Local clock HH:MM (Asia/Shanghai), inclusive start
   */
  start: string;
  /**
   * Local clock HH:MM (Asia/Shanghai), exclusive end
   */
  end: string;
  /**
   * Exchange this session belongs to
   */
  exchange: "SH" | "SZ" | "BJ";
  /**
   * True when the session ends after midnight (start > end); it belongs to its start trading day
   */
  crossesMidnight?: boolean;
}

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

/**
 * Adjustment factor applied on ex-date to derive adjusted research prices
 */
export interface AdjustmentFactor {
  /**
   * Instrument unified code, e.g. SH.600000
   */
  unifiedCode: string;
  /**
   * Exchange code
   */
  exchange: "SH" | "SZ" | "BJ";
  /**
   * Ex-dividend date in Asia/Shanghai
   */
  date: string;
  /**
   * Adjustment factor, must be strictly > 0
   */
  factor: number;
  /**
   * FORWARD / BACKWARD adjustment
   */
  factorType: "FORWARD" | "BACKWARD";
  /**
   * Optional free-text note
   */
  note?: string;
}

/**
 * OHLCV bar with explicit price type; adjusted (research) and raw (trade) prices stay separate
 */
export interface Bar {
  /**
   * Instrument unified code, e.g. SH.600000
   */
  unifiedCode: string;
  /**
   * Exchange code
   */
  exchange: "SH" | "SZ" | "BJ";
  /**
   * Trading day in Asia/Shanghai, e.g. 2026-08-13
   */
  date: string;
  /**
   * Bar interval: DAILY / MINUTE_1 / MINUTE_5
   */
  interval: "DAILY" | "MINUTE_1" | "MINUTE_5";
  /**
   * Session the bar belongs to
   */
  session: "CONTINUOUS" | "OPEN_AUCTION" | "CLOSE_AUCTION";
  /**
   * Bar start time, UTC ISO 8601 with millisecond precision
   */
  timestamp: string;
  /**
   * Open price in CNY
   */
  open: number;
  /**
   * High price in CNY
   */
  high: number;
  /**
   * Low price in CNY
   */
  low: number;
  /**
   * Close price in CNY
   */
  close: number;
  /**
   * Volume in shares
   */
  volume: number;
  /**
   * Turnover in CNY
   */
  amount: number;
  /**
   * RAW (trade price) / FORWARD_ADJUSTED / BACKWARD_ADJUSTED (research price)
   */
  priceType: "RAW" | "FORWARD_ADJUSTED" | "BACKWARD_ADJUSTED";
  /**
   * True when the instrument was suspended for this bar
   */
  suspended?: boolean;
}

/**
 * A corporate action event: dividend, stock dividend, split or rights issue
 */
export interface CorporateAction {
  /**
   * Instrument unified code, e.g. SH.600000
   */
  unifiedCode: string;
  /**
   * Exchange code
   */
  exchange: "SH" | "SZ" | "BJ";
  /**
   * Ex-date in Asia/Shanghai
   */
  exDate: string;
  /**
   * DIVIDEND / STOCK_DIVIDEND / SPLIT / RIGHTS_ISSUE
   */
  actionType: "DIVIDEND" | "STOCK_DIVIDEND" | "SPLIT" | "RIGHTS_ISSUE";
  /**
   * Human-readable description
   */
  description: string;
  /**
   * Cash dividend per share in CNY (optional)
   */
  perShareCash?: number;
  /**
   * Stock dividend per share (optional)
   */
  perShareStock?: number;
  /**
   * Rights issue ratio (optional)
   */
  ratio?: number;
}

/**
 * A single executed trade with millisecond-precision timestamp
 */
export interface Tick {
  /**
   * Instrument unified code, e.g. SH.600000
   */
  unifiedCode: string;
  /**
   * Exchange code
   */
  exchange: "SH" | "SZ" | "BJ";
  /**
   * Trading day in Asia/Shanghai, e.g. 2026-08-13
   */
  date: string;
  /**
   * Trade time, UTC ISO 8601 with millisecond precision
   */
  timestamp: string;
  /**
   * Trade price in CNY
   */
  price: number;
  /**
   * Trade volume in shares
   */
  volume: number;
  /**
   * Trade turnover in CNY
   */
  amount: number;
  /**
   * Aggressor direction: BUY / SELL / NEUTRAL
   */
  direction: "BUY" | "SELL" | "NEUTRAL";
  /**
   * MATCH / AUCTION / BLOCK
   */
  tradeType: "MATCH" | "AUCTION" | "BLOCK";
}
