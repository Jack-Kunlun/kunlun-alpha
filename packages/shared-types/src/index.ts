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
 * Immutable, versioned raw content record for news, announcements, research, interactive and social content. publishTime <= ingestTime <= availableTime (all timezone-aware). recordId identifies the content lineage; versionId identifies the current immutable version; previousVersionId links the direct predecessor. The content fingerprint is a deterministic 64-hex SHA-256 that the domain recomputes (never trusted from the wire). Updates and deletions never overwrite history.
 */
export interface RawContent {
  /**
   * Content category: NEWS / ANNOUNCEMENT / RESEARCH / INTERACTION / SOCIAL
   */
  contentType: "NEWS" | "ANNOUNCEMENT" | "RESEARCH" | "INTERACTION" | "SOCIAL";
  /**
   * Stable identifier of the content lineage; shared by every version
   */
  recordId: string;
  /**
   * Unique identifier of the current immutable version (64-hex SHA-256)
   */
  versionId: string;
  /**
   * Original URL or source locator for the raw content
   */
  url: string;
  /**
   * Original raw title
   */
  title: string;
  /**
   * Original raw body
   */
  body: string;
  /**
   * When the content was published (timezone-aware)
   */
  publishTime: string;
  /**
   * When Kunlun ingested the content (timezone-aware)
   */
  ingestTime: string;
  /**
   * Earliest time this record may enter research or downstream computation
   */
  availableTime: string;
  /**
   * Deterministic 64-hex lowercase SHA-256 content fingerprint
   */
  fingerprint: string;
  /**
   * Fingerprint algorithm version
   */
  fingerprintAlgorithmVersion: "sha256-v1";
  source: ContentSource;
  license: LicenseMetadata;
  originalSource?: ContentSource1;
  /**
   * versionId of the direct predecessor; null for the first version
   */
  previousVersionId?: string | null;
  /**
   * Whether this content has been deleted; deletion preserves evidence
   */
  deleted: boolean;
  /**
   * Deletion time; required when deleted is true, and not before availableTime
   */
  deletedAt?: string | null;
}
/**
 * Current source attribution
 */
export interface ContentSource {
  /**
   * Source provider or platform identifier
   */
  sourceId: string;
  /**
   * Provider data/API version
   */
  sourceVersion: string;
  /**
   * Immutable identifier of the raw evidence this content derives from
   */
  evidenceId: string;
}
/**
 * License, authorization and usage-restriction metadata
 */
export interface LicenseMetadata {
  /**
   * License or right-grant identifier
   */
  licenseId: string;
  /**
   * Usage restriction; a non-restricting license states it explicitly
   */
  usageRestriction: string;
  /**
   * Explicit authorization; usable only when true
   */
  authorized: boolean;
}
/**
 * Original source for a repost; absent for non-repost content
 */
export interface ContentSource1 {
  /**
   * Source provider or platform identifier
   */
  sourceId: string;
  /**
   * Provider data/API version
   */
  sourceVersion: string;
  /**
   * Immutable identifier of the raw evidence this content derives from
   */
  evidenceId: string;
}

/**
 * A single limit-up/limit-down fact: seal, seal break, or open count
 */
export interface LimitEvent {
  /**
   * Instrument unified code
   */
  unifiedCode: string;
  /**
   * Exchange code
   */
  exchange: "SH" | "SZ" | "BJ";
  /**
   * Trading day in Asia/Shanghai
   */
  date: string;
  /**
   * LIMIT_UP / LIMIT_DOWN / SEAL / BREAK_SEAL / OPEN_COUNT
   */
  eventType: "LIMIT_UP" | "LIMIT_DOWN" | "SEAL" | "BREAK_SEAL" | "OPEN_COUNT";
  /**
   * Event time, UTC ISO 8601
   */
  timestamp: string;
  /**
   * Event price in CNY
   */
  price: number;
  /**
   * Number of times the seal has been opened
   */
  openCount?: number;
}

/**
 * A point-in-time snapshot of the limit-up/limit-down pool
 */
export interface LimitPoolSnapshot {
  /**
   * Trading day in Asia/Shanghai
   */
  date: string;
  /**
   * Snapshot time, UTC ISO 8601
   */
  timestamp: string;
  /**
   * Number of limit-up instruments
   */
  limitUpCount: number;
  /**
   * Number of limit-down instruments
   */
  limitDownCount: number;
  /**
   * Number of sealed (unopened) limit-up instruments
   */
  sealedCount: number;
  /**
   * Limit-up unified codes
   */
  limitUpInstruments?: string[];
  /**
   * Limit-down unified codes
   */
  limitDownInstruments?: string[];
  /**
   * Earliest first-seal event time across the pool, UTC ISO 8601, or null when none sealed
   */
  firstSealTime?: string | null;
  /**
   * Latest seal event time across the pool, UTC ISO 8601, or null when none sealed
   */
  lastSealTime?: string | null;
  /**
   * Total number of seal openings (break-then-reseal) across the pool
   */
  totalOpenCount?: number;
}

/**
 * Point-in-time fund NAV/iNAV reference observation; values are not executable prices
 */
export interface FundNav {
  /**
   * Instrument unified code, e.g. 518880.SH
   */
  unifiedCode: string;
  /**
   * NAV reference date in Asia/Shanghai
   */
  date: string;
  /**
   * Net asset value reference amount
   */
  nav: number;
  /**
   * Indicative NAV reference amount, when available
   */
  inav: number | null;
  /**
   * Economic observation/event time (timezone required)
   */
  eventTime: string;
  /**
   * Provider publication time (timezone required)
   */
  publishTime: string;
  /**
   * Kunlun ingest time (timezone required)
   */
  ingestTime: string;
  /**
   * Earliest research availability time (timezone required)
   */
  availableTime: string;
  /**
   * Normalization/processing time (timezone required)
   */
  processingTime: string;
  /**
   * Immutable raw evidence/object identifier
   */
  rawObjectId: string;
  /**
   * Data source provenance identifier
   */
  source: string;
}

/**
 * Exchange-listed precious-metal fund metadata with explicit classification, currency, provenance and validity semantics; NAV/iNAV remain reference data and are never executable prices
 */
export interface PreciousMetalFund {
  /**
   * Instrument unified code, e.g. 518880.SH
   */
  unifiedCode: string;
  /**
   * Exchange code
   */
  exchange: "SH" | "SZ" | "BJ";
  /**
   * Exchange-listed fund asset type
   */
  assetType: "ETF" | "LOF" | "FUND";
  /**
   * Fund asset class; commodity values belong in underlyingCommodity
   */
  fundAssetClass: "PRECIOUS_METALS";
  /**
   * Underlying commodity, explicit and never inferred from product name
   */
  underlyingCommodity: "GOLD" | "SILVER" | "OTHER";
  /**
   * Currency used for exchange trading
   */
  tradingCurrency: "CNY";
  /**
   * Currency in which NAV/iNAV is reported
   */
  navCurrency: string;
  /**
   * Benchmark or tracking index identifier
   */
  benchmarkOrTrackingIndex: string;
  /**
   * Annual management fee rate in [0, 1]
   */
  managementFeeRate: number;
  /**
   * Start of classification validity interval
   */
  validFrom: string;
  /**
   * End of classification validity interval; null means currently valid
   */
  validTo?: string | null;
  /**
   * Data source provenance identifier
   */
  source: string;
  /**
   * Optional provider event time for the classification record
   */
  eventTime?: string;
  /**
   * Provider publication time for the classification record
   */
  publishTime: string;
  /**
   * Kunlun ingest time for the classification record
   */
  ingestTime: string;
  /**
   * Earliest point-in-time availability for the classification record
   */
  availableTime: string;
  /**
   * Normalization/processing time for the classification record
   */
  processingTime: string;
  /**
   * Immutable raw evidence/object identifier
   */
  rawObjectId: string;
  /**
   * Optional recurring fee records; each rate remains source-traceable
   */
  recurringFees?: {
    /**
     * Fee kind, e.g. custody or administration
     */
    kind: string;
    /**
     * Annual fee rate in [0, 1]
     */
    rate: number;
    validFrom: string;
    validTo?: string | null;
    /**
     * Fee source provenance identifier
     */
    source: string;
  }[];
  /**
   * Classification confidence in [0, 1]
   */
  confidence: number;
  /**
   * Human/data-quality review status
   */
  reviewStatus: "UNREVIEWED" | "NEEDS_REVIEW" | "REVIEWED" | "REJECTED";
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
   * Exchange code used in the unified instrument code (600000.SH)
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
   * Unified domain key in the form {code}.{EXCHANGE}, e.g. 600000.SH
   */
  unifiedCode: string;
  /**
   * Raw 6-digit exchange code
   */
  code: string;
  /**
   * Exchange code; must match the unifiedCode suffix
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
   * Instrument unified code, e.g. 600000.SH
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
   * Instrument unified code, e.g. 600000.SH
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
   * Instrument unified code, e.g. 600000.SH
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
   * Instrument unified code, e.g. 600000.SH
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

/**
 * An instrument's membership in a sector, with a validity window and source
 */
export interface SectorMembership {
  /**
   * Instrument unified code
   */
  unifiedCode: string;
  /**
   * Sector id
   */
  sectorId: string;
  /**
   * Start of membership validity
   */
  validFrom: string;
  /**
   * End of membership validity, null means current
   */
  validTo?: string | null;
  /**
   * Data source provenance
   */
  source: string;
}

/**
 * A sector node in the taxonomy: industry, concept or theme with hierarchy, aliases and validity
 */
export interface Sector {
  /**
   * Stable sector id
   */
  sectorId: string;
  /**
   * Display name
   */
  name: string;
  /**
   * Parent sector id (null for a root)
   */
  parentId?: string | null;
  /**
   * INDUSTRY / CONCEPT / THEME
   */
  kind: "INDUSTRY" | "CONCEPT" | "THEME";
  /**
   * Data source provenance
   */
  source: string;
  /**
   * Start of validity
   */
  validFrom: string;
  /**
   * End of validity, null means current
   */
  validTo?: string | null;
  /**
   * Alternative names
   */
  aliases: string[];
}
