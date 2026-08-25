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
 * Versioned persisted market-emotion snapshot for real-time and historical replay
 */
export interface MarketEmotionSnapshot {
  date: string;
  timestamp: string;
  score: number;
  algorithmVersion: string;
  ladder: {
    board: number;
    count: number;
  }[];
  freshnessSeconds: number;
  sampleSize: number;
  confidence: number;
  sourceVersions: string[];
  evidenceIds: string[];
}

export interface EventFeedbackSubmission {
  schemaVersion: "event-feedback-submission-v1";
  clientRequestId: string;
  eventId: string;
  modelConfigurationFingerprint: string;
  action: "CONFIRM" | "REJECT" | "CORRECT";
  reasonCode:
    | "ACCURATE"
    | "WRONG_TYPE"
    | "WRONG_ENTITY"
    | "WRONG_EVIDENCE"
    | "DUPLICATE"
    | "NOT_MARKET_EVENT"
    | "OTHER";
  correction?: Correction;
  comment?: string;
}
export interface Correction {
  eventType?:
    | "CORPORATE"
    | "EARNINGS"
    | "FINANCING"
    | "REGULATORY"
    | "POLICY"
    | "MACRO"
    | "INDUSTRY"
    | "MARKET"
    | "RISK"
    | "OTHER";
  headline?: string;
  summary?: string;
  instrumentIds?: string[];
  sectorIds?: string[];
  evidenceIds?: string[];
}

export interface EventFeedback {
  schemaVersion: "event-feedback-v1";
  feedbackId: string;
  clientRequestId: string;
  eventId: string;
  modelConfigurationFingerprint: string;
  action: "CONFIRM" | "REJECT" | "CORRECT";
  reasonCode:
    | "ACCURATE"
    | "WRONG_TYPE"
    | "WRONG_ENTITY"
    | "WRONG_EVIDENCE"
    | "DUPLICATE"
    | "NOT_MARKET_EVENT"
    | "OTHER";
  correction?: Correction;
  comment?: string;
  reviewerRef: string;
  submissionFingerprint: string;
  createdAt: string;
  availableAt: string;
}
export interface Correction {
  eventType?:
    | "CORPORATE"
    | "EARNINGS"
    | "FINANCING"
    | "REGULATORY"
    | "POLICY"
    | "MACRO"
    | "INDUSTRY"
    | "MARKET"
    | "RISK"
    | "OTHER";
  headline?: string;
  summary?: string;
  instrumentIds?: string[];
  sectorIds?: string[];
  evidenceIds?: string[];
}

export interface HotTopicSnapshot {
  schemaVersion: "hot-topic-snapshot-v1";
  snapshotId: string;
  topicId: string;
  topicName: string;
  lifecycle: "EMERGING" | "RISING" | "HOT" | "COOLING" | "DORMANT";
  decisionTime: string;
  windowStart: string;
  windowEnd: string;
  scoreBps: number;
  confidenceBps: number;
  components: {
    evidenceQualityBps: number;
    recencyBps: number;
    sourceDiversityBps: number;
    breadthBps: number;
    momentumBps: number;
  };
  eventCount: number;
  recentEventCount: number;
  staleEventCount: number;
  sourceCount: number;
  instrumentCount: number;
  sectorCount: number;
  eventIds: string[];
  policyFingerprint: string;
  previousSnapshotId?: string | null;
  algorithmVersion: "hot-score-v1";
}

export type MarketEventType =
  | "CORPORATE"
  | "EARNINGS"
  | "FINANCING"
  | "REGULATORY"
  | "POLICY"
  | "MACRO"
  | "INDUSTRY"
  | "MARKET"
  | "RISK"
  | "OTHER";
export type ProducerType = "MODEL" | "RULE";

/**
 * Immutable, versioned market event with point-in-time evidence and model provenance
 */
export interface MarketEvent {
  /**
   * Persistent MarketEvent contract version
   */
  schemaVersion: "market-event-v1";
  /**
   * Domain-derived SHA-256 identity over every immutable event fact
   */
  eventId: string;
  eventType: MarketEventType;
  headline: string;
  summary: string;
  /**
   * Business occurrence time; it may be in the future for announced plans
   */
  occurTime: string;
  publishTime: string;
  /**
   * Earliest instant the validated event may enter downstream computation
   */
  availableTime: string;
  instrumentIds: string[];
  sectorIds: string[];
  /**
   * @minItems 1
   */
  evidence: [EvidenceReference, ...EvidenceReference[]];
  modelProvenance: ModelProvenance;
  /**
   * Integer basis-point confidence; never a binary float
   */
  confidenceBps: number;
}
export interface EvidenceReference {
  evidenceId: string;
  contentRecordId: string;
  contentVersionId: string;
  sourceId: string;
  sourceVersion: string;
  availableTime: string;
  startOffset: number;
  endOffset: number;
  excerpt: string;
}
export interface ModelProvenance {
  producerType: ProducerType;
  provider: string;
  modelId: string;
  modelVersion: string;
  promptVersion: string;
  outputSchemaVersion: "market-event-v1";
  configurationFingerprint: string;
  extractionRunId: string;
  processingTime: string;
}

export interface FeatureSpec {
  schemaVersion: "feature-spec-v1";
  name: string;
  version: string;
  entity: "INSTRUMENT" | "SECTOR" | "MARKET" | "EVENT" | "SEAT" | "KOL" | "PRECIOUS_METALS_FUND";
  frequency: "TICK" | "MINUTE" | "DAILY" | "EVENT" | "SNAPSHOT";
  valueType: "BOOLEAN" | "INTEGER" | "DECIMAL" | "STRING" | "CATEGORY" | "VECTOR";
  owner: string;
  description: string;
  algorithmVersion: string;
  calculationDefinition: string;
  windowDefinition: string;
  filterPolicyVersion: string;
  pitPolicyVersion: string;
  eventTimeField: string;
  availableTimeField: string;
  availabilityPolicy: "SOURCE_AVAILABLE_TIME" | "MAX_INPUT_AVAILABLE_TIME" | "MATERIALIZATION_TIME";
  dependencies: {
    [k: string]: string;
  };
  sourceContracts: {
    [k: string]: string;
  };
  semanticFingerprint: string;
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

export type ClaimAction = "BUY" | "SELL" | "HOLDING" | "WATCH";
export type ClaimPolarity = "AFFIRMED" | "NEGATED";
export type ClaimConditionality = "UNCONDITIONAL" | "CONDITIONAL";
export type ClaimStatementKind = "DIRECT" | "QUOTE" | "PARAPHRASE" | "AMBIGUOUS";
export type ClaimAttribution = "SELF" | "QUOTED" | "REPORTED" | "UNKNOWN";
export type EventTimeStatus = "EXACT" | "DATE_ONLY" | "UNKNOWN";
export type EvidenceGrade =
  "PRIMARY_SOURCE" | "SECONDARY_SOURCE" | "TERTIARY_SOURCE" | "UNCLASSIFIED";

/**
 * An unreviewed public-speech extraction candidate. It is not a fact, Trade, order, fill, account or executable position.
 */
export interface KolClaimExtractionCandidate {
  schemaVersion: "claim-extraction-candidate-v1";
  candidateId: string;
  revisionId: string;
  previousRevisionId: string | null;
  semanticLabel: "PUBLIC_SPEECH_CANDIDATE_NOT_FACT_OR_EXECUTION";
  statement: string;
  action: ClaimAction;
  polarity: ClaimPolarity;
  conditionality: ClaimConditionality;
  statementKind: ClaimStatementKind;
  attribution: ClaimAttribution;
  eventTimeStatus: EventTimeStatus;
  eventTime: string | null;
  eventDate: string | null;
  instrumentId: string;
  /**
   * @minItems 1
   * @maxItems 32
   */
  anchors: [ContentExactAnchor | MediaExactAnchor, ...(ContentExactAnchor | MediaExactAnchor)[]];
  evidenceGrade: EvidenceGrade;
  evidenceGradeVersion: "evidence-grade-v1";
  confidenceBps: number;
  source: string;
  sourceVersion: string;
  algorithmVersion: "kol-claim-extraction-v1";
  promptVersion: string;
  modelProvider: string;
  modelVersion: string;
  configurationFingerprint: string;
  policyFingerprint: string;
  recognitionRunId: string;
  publishTime: string;
  ingestTime: string;
  processingTime: string;
  availableTime: string;
  reviewStatus: "UNREVIEWED";
  deleted: boolean;
  deletedAt: string | null;
  deletionReason: string | null;
}
export interface ContentExactAnchor {
  anchorType: "CONTENT";
  sourceIndex: number;
  contentId: string;
  contentVersion: string;
  contentRevisionId: string;
  contentAvailableTime: string;
  source: string;
  sourceVersion: string;
  startOffset: number;
  endOffset: number;
  excerpt: string;
  evidenceGrade: EvidenceGrade;
  evidenceGradeVersion: "evidence-grade-v1";
}
export interface MediaExactAnchor {
  anchorType: "MEDIA";
  sourceIndex: number;
  contentId: string;
  contentVersion: string;
  contentRevisionId: string;
  contentAvailableTime: string;
  source: string;
  sourceVersion: string;
  startOffset: number;
  endOffset: number;
  excerpt: string;
  evidenceGrade: EvidenceGrade;
  evidenceGradeVersion: "evidence-grade-v1";
  evidenceId: string;
  evidenceRevisionId: string;
  evidenceAvailableTime: string;
  mediaId: string;
  mediaVersion: string;
  mediaManifestRevisionId: string;
  /**
   * @minItems 1
   * @maxItems 1000
   */
  segmentIndexes: [number, ...number[]];
}

/**
 * Client request for a server-owned append-only human review of an exact candidate revision.
 */
export interface KolClaimReviewSubmission {
  schemaVersion: "claim-review-submission-v1";
  clientRequestId: string;
  candidateId: string;
  candidateRevisionId: string;
  decision: "IN_REVIEW" | "APPROVED" | "REJECTED";
  reason: string;
  comment?: string | null;
  expectedPreviousReviewId?: string | null;
}

/**
 * Immutable server-owned human review of an exact unreviewed public-speech candidate. Approval is not fact verification or execution confirmation.
 */
export interface KolClaimReview {
  schemaVersion: "claim-review-v1";
  reviewId: string;
  candidateId: string;
  candidateRevisionId: string;
  decision: "IN_REVIEW" | "APPROVED" | "REJECTED";
  reason: string;
  comment: string | null;
  reviewerRef: string;
  createdAt: string;
  availableAt: string;
  submissionFingerprint: string;
  previousReviewId: string | null;
  reviewMeaning: "PUBLIC_WORDING_REVIEWED_NOT_FACT_OR_EXECUTION";
}

export type KolClaimSchemaVersion = "kol-claim-v1";
export type KolClaimStatementKind = "DIRECT" | "QUOTE" | "PARAPHRASE" | "AMBIGUOUS";
export type KolClaimDirection = "BULLISH" | "BEARISH" | "NEUTRAL";
export type KolClaimAttribution = "SELF" | "QUOTED" | "REPORTED" | "UNKNOWN";
export type KolClaimUncertainty = "NONE" | "AMBIGUOUS" | "CONDITIONAL" | "UNVERIFIED";
export type KolClaimReviewStatus = "UNREVIEWED" | "IN_REVIEW" | "APPROVED" | "REJECTED";

/**
 * Versioned, reviewable KOL statement with evidence. A claim is not a Trade, order, fill, position fact or broker confirmation.
 */
export interface KolClaim {
  schemaVersion: KolClaimSchemaVersion;
  claimId: string;
  revisionId: string;
  previousRevisionId: string | null;
  contentId: string;
  contentVersion: string;
  contentAvailableTime: string;
  kolId: string;
  statement: string;
  statementKind: KolClaimStatementKind;
  instrumentId: string;
  direction: KolClaimDirection;
  attribution: KolClaimAttribution;
  uncertainty: KolClaimUncertainty;
  confidenceBps: number;
  reviewStatus: KolClaimReviewStatus;
  eventTime: string;
  publishTime: string;
  ingestTime: string;
  processingTime: string;
  availableTime: string;
  source: string;
  sourceVersion: string;
  /**
   * @minItems 1
   */
  evidence: [KolClaimEvidenceReference, ...KolClaimEvidenceReference[]];
  deleted: boolean;
  deletedAt: string | null;
  deletionReason: string | null;
}
export interface KolClaimEvidenceReference {
  evidenceId: string;
  evidenceRevisionId: string;
  contentId: string;
  contentVersion: string;
  contentAvailableTime: string;
  evidenceAvailableTime: string;
  source: string;
  sourceVersion: string;
}

export type KolContentSchemaVersion = "kol-content-v1";
export type KolContentType = "POST" | "ARTICLE" | "VIDEO" | "AUDIO" | "COMMENT" | "OTHER";
export type KolContentFingerprintAlgorithmVersion = "sha256-kol-content-v1";

/**
 * Immutable, versioned public KOL content. Content is source material, not a trade or execution fact.
 */
export interface KolContent {
  schemaVersion: KolContentSchemaVersion;
  contentId: string;
  contentVersion: string;
  revisionId: string;
  previousRevisionId: string | null;
  kolId: string;
  contentType: KolContentType;
  title: string;
  body: string;
  contentFingerprint: string;
  contentFingerprintAlgorithmVersion: KolContentFingerprintAlgorithmVersion;
  eventTime: string | null;
  publishTime: string;
  ingestTime: string;
  processingTime: string;
  availableTime: string;
  source: string;
  sourceVersion: string;
  deleted: boolean;
  deletedAt: string | null;
  deletionReason: string | null;
}

export type KolEvidenceSchemaVersion = "kol-evidence-v1";
export type KolEvidenceLocatorType = "URL" | "TEXT_RANGE" | "TIME_RANGE" | "PAGE";
export type KolEvidenceGrade =
  "PRIMARY_SOURCE" | "SECONDARY_SOURCE" | "TERTIARY_SOURCE" | "UNCLASSIFIED";
export type KolEvidenceGradeVersion = "evidence-grade-v1";

/**
 * Immutable evidence locator bound to one exact KOL content version.
 */
export interface KolEvidence {
  schemaVersion: KolEvidenceSchemaVersion;
  evidenceId: string;
  revisionId: string;
  previousRevisionId: string | null;
  contentId: string;
  contentVersion: string;
  contentAvailableTime: string;
  source: string;
  sourceVersion: string;
  locatorType: KolEvidenceLocatorType;
  locator: string;
  excerpt: string;
  evidenceGrade: KolEvidenceGrade;
  evidenceGradeVersion: KolEvidenceGradeVersion;
  availableTime: string;
}

export type MediaTextEvidenceSchemaVersion = "kol-media-text-evidence-v1";
export type MediaKind = "AUDIO" | "VIDEO" | "IMAGE";
export type MediaProcessorKind = "ASR" | "OCR";

/**
 * Versioned, locator-addressable ASR/OCR text evidence derived from an authorized immutable media version. It is input to later claim extraction, never a Claim, Trade or execution fact.
 */
export interface KolMediaTextEvidence {
  schemaVersion: MediaTextEvidenceSchemaVersion;
  evidenceId: string;
  revisionId: string;
  previousRevisionId: string | null;
  mediaManifest: MediaManifest;
  processorKind: MediaProcessorKind;
  text: string;
  language: string;
  /**
   * @minItems 1
   * @maxItems 100000
   */
  segments: [MediaTextSegment, ...MediaTextSegment[]];
  confidenceBps: number;
  qualityBps: number;
  eventTime: string | null;
  publishTime: string;
  ingestTime: string;
  processingTime: string;
  availableTime: string;
  provenance: MediaEvidenceProvenance;
  deleted: boolean;
  deletedAt: string | null;
  deletionReason: string | null;
}
export interface MediaManifest {
  contentId: string;
  contentVersion: string;
  mediaId: string;
  mediaVersion: string;
  revisionId: string;
  previousRevisionId: string | null;
  rawSha256: string;
  mimeType: string;
  byteSize: number;
  mediaKind: MediaKind;
  source: string;
  sourceVersion: string;
  licenseId: string;
  usageRestriction: string;
  authorized: boolean;
  inputAvailableTime: string;
  width: number | null;
  height: number | null;
  durationMs: number | null;
  deleted: boolean;
  deletedAt: string | null;
  deletionReason: string | null;
}
export interface MediaTextSegment {
  text: string;
  startOffset: number;
  endOffset: number;
  startMs: number | null;
  endMs: number | null;
  bbox: MediaBoundingBox | null;
  frameIdentity?: string | null;
  confidenceBps: number;
  qualityBps: number;
}
export interface MediaBoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}
export interface MediaEvidenceProvenance {
  pipelineVersion: string;
  processorKind: MediaProcessorKind;
  provider: string;
  model: string;
  modelVersion: string;
  promptVersion: string;
  configurationFingerprint: string;
  policyFingerprint: string;
  recognitionRunId: string;
}

export type KolMentionSchemaVersion = "kol-mention-v1";
export type KolMentionType = "INSTRUMENT" | "PERSON" | "ORGANIZATION" | "TOPIC" | "OTHER";

/**
 * Immutable occurrence/reference inside a KOL content version. A mention is not an assertion or claim.
 */
export interface KolMention {
  schemaVersion: KolMentionSchemaVersion;
  mentionId: string;
  revisionId: string;
  previousRevisionId: string | null;
  contentId: string;
  contentVersion: string;
  kolId: string;
  mentionType: KolMentionType;
  surfaceText: string;
  startOffset: number;
  endOffset: number;
  availableTime: string;
  source: string;
  sourceVersion: string;
}

export type KolPositionClaimSchemaVersion = "kol-position-claim-v1";
export type KolPositionDirection = "LONG" | "SHORT" | "FLAT";
export type KolPositionTimeHorizon = "INTRADAY" | "SWING" | "LONG_TERM" | "UNSPECIFIED";
export type KolExecutionSemantics = "NON_EXECUTABLE_POSITION_CLAIM";
export type KolPositionReviewStatus = "UNREVIEWED" | "IN_REVIEW" | "APPROVED" | "REJECTED";

/**
 * Versioned non-executable position interpretation linked to one exact Claim revision.
 */
export interface KolPositionClaim {
  schemaVersion: KolPositionClaimSchemaVersion;
  positionClaimId: string;
  revisionId: string;
  previousRevisionId: string | null;
  claimId: string;
  claimRevisionId: string;
  kolId: string;
  instrumentId: string;
  position: KolPositionDirection;
  timeHorizon: KolPositionTimeHorizon;
  executionSemantics: KolExecutionSemantics;
  confidenceBps: number;
  reviewStatus: KolPositionReviewStatus;
  eventTime: string;
  publishTime: string;
  ingestTime: string;
  processingTime: string;
  availableTime: string;
  source: string;
  sourceVersion: string;
  deleted: boolean;
  deletedAt: string | null;
  deletionReason: string | null;
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

export interface SeatKolWorkbenchSnapshot {
  schemaVersion: "seat-kol-workbench-v1";
  snapshotId: string;
  decisionTime: string;
  dataCutoffTime: string;
  sourceVersion: string;
  mode: "PERSISTED" | "LOCAL_PREVIEW";
  dataMeaning: "RESEARCH_ONLY_PUBLIC_DATA_NOT_BROKER_EXECUTION";
  seats: SeatWorkbenchProfile[];
  kols: KolWorkbenchProfile[];
  cooccurrences: SeatKolCooccurrence[];
  reviewQueue: KolReviewQueueItem[];
}
export interface SeatWorkbenchProfile {
  seatId: string;
  displayName: string;
  seatKind: "BROKER_BRANCH" | "INSTITUTION" | "UNKNOWN" | "OTHER";
  aliases: string[];
  /**
   * @minItems 1
   */
  metrics: [SeatKolWorkbenchMetric, ...SeatKolWorkbenchMetric[]];
  /**
   * @minItems 1
   */
  evidence: [SeatKolWorkbenchEvidence, ...SeatKolWorkbenchEvidence[]];
  timeline: SeatKolWorkbenchTimelineEntry[];
}
export interface SeatKolWorkbenchMetric {
  metricName:
    | "seat_t_plus_1_return_bps"
    | "seat_t_plus_3_return_bps"
    | "seat_win_rate_bps"
    | "kol_attention_score"
    | "consensus_score"
    | "claim_score";
  label: string;
  valueBps: number | null;
  sampleCount: number;
  confidenceBps: number;
  algorithmVersion: string;
  policyVersion: string;
  dataCutoffTime: string;
}
export interface SeatKolWorkbenchEvidence {
  evidenceId: string;
  source: string;
  sourceVersion: string;
  availableTime: string;
  excerpt: string;
  locator: string;
}
export interface SeatKolWorkbenchTimelineEntry {
  entryId: string;
  kind: "PROFILE" | "PUBLIC_TRADE" | "CLAIM" | "REVIEW" | "METRIC";
  occurTime: string;
  availableTime: string;
  title: string;
  /**
   * @minItems 1
   */
  evidenceIds: [string, ...string[]];
}
export interface KolWorkbenchProfile {
  kolId: string;
  displayName: string;
  /**
   * @minItems 1
   */
  metrics: [SeatKolWorkbenchMetric, ...SeatKolWorkbenchMetric[]];
  claims: KolWorkbenchClaim[];
  /**
   * @minItems 1
   */
  evidence: [SeatKolWorkbenchEvidence, ...SeatKolWorkbenchEvidence[]];
  timeline: SeatKolWorkbenchTimelineEntry[];
}
export interface KolWorkbenchClaim {
  claimId: string;
  revisionId: string;
  statement: string;
  instrumentId: string;
  direction: "BULLISH" | "BEARISH" | "NEUTRAL";
  reviewStatus: "UNREVIEWED" | "IN_REVIEW" | "APPROVED" | "REJECTED";
  confidenceBps: number;
  publishTime: string;
  availableTime: string;
  deleted: boolean;
  claimMeaning: "PUBLIC_WORDING_CLAIM_NOT_BROKER_TRADE";
  /**
   * @minItems 1
   */
  evidence: [SeatKolWorkbenchEvidence, ...SeatKolWorkbenchEvidence[]];
}
export interface SeatKolCooccurrence {
  cooccurrenceId: string;
  leftEntityType: "SEAT" | "KOL";
  leftEntityId: string;
  leftDisplayName: string;
  rightEntityType: "SEAT" | "KOL";
  rightEntityId: string;
  rightDisplayName: string;
  scoreBps: number;
  sampleCount: number;
  algorithmVersion: string;
  policyVersion: string;
  dataCutoffTime: string;
  /**
   * @minItems 1
   */
  evidenceIds: [string, ...string[]];
}
export interface KolReviewQueueItem {
  candidateId: string;
  revisionId: string;
  statement: string;
  instrumentId: string;
  confidenceBps: number;
  reviewStatus: "UNREVIEWED" | "IN_REVIEW" | "APPROVED" | "REJECTED";
  availableTime: string;
  reviewMeaning: "PUBLIC_WORDING_REVIEW_NOT_FACT_OR_EXECUTION";
  /**
   * @minItems 1
   */
  evidence: [SeatKolWorkbenchEvidence, ...SeatKolWorkbenchEvidence[]];
}

export type SeatAliasSchemaVersion = "alias-v1";
export type SeatAliasType = "OFFICIAL" | "FORMER" | "SOURCE" | "ALTERNATE";

/**
 * Immutable source/display name alias with a half-open business-validity interval.
 */
export interface SeatAlias {
  schemaVersion: SeatAliasSchemaVersion;
  aliasId: string;
  seatId: string;
  name: string;
  aliasType: SeatAliasType;
  validFrom: string;
  /**
   * Exclusive business-validity end; null means open-ended
   */
  validTo: string | null;
  availableTime: string;
  source: string;
  sourceVersion: string;
  evidenceId: string;
  revisionId: string;
  previousRevisionId: string | null;
}

export type SeatPerformanceSchemaVersion = "seat-performance-v1";

/**
 * Versioned seat performance snapshot. Calculation is owned by a later node.
 */
export interface SeatPerformance {
  schemaVersion: SeatPerformanceSchemaVersion;
  performanceId: string;
  seatId: string;
  windowStart: string;
  windowEnd: string;
  calculationVersion: string;
  sampleCount: number;
  tPlus1Return: string | null;
  tPlus3Return: string | null;
  tPlus5Return: string | null;
  winRate: string | null;
  maxDrawdown: string | null;
  source: string;
  sourceVersion: string;
  evidenceId: string;
  revisionId: string;
  previousRevisionId: string | null;
  availableTime: string;
}

export type SeatPreferenceSchemaVersion = "seat-preference-v1";

/**
 * Versioned provenance-backed seat style preference snapshot.
 */
export interface SeatPreference {
  schemaVersion: SeatPreferenceSchemaVersion;
  preferenceId: string;
  seatId: string;
  validFrom: string;
  /**
   * Exclusive business-validity end; null means open-ended
   */
  validTo: string | null;
  preferenceVersion: string;
  /**
   * @minItems 1
   */
  styleTags: [string, ...string[]];
  confidenceBps: number;
  source: string;
  sourceVersion: string;
  evidenceId: string;
  revisionId: string;
  previousRevisionId: string | null;
  availableTime: string;
}

export type SeatProfileSchemaVersion = "seat-profile-v1";
export type SeatProfileSeatKind = "BROKER_BRANCH" | "INSTITUTION" | "UNKNOWN" | "OTHER";
export type SeatProfileLineageRelation = "MERGE" | "SPLIT";

/**
 * Versioned stable seat identity profile. Display names are mutable evidence, not identity.
 */
export interface SeatProfile {
  schemaVersion: SeatProfileSchemaVersion;
  seatId: string;
  /**
   * Single v1 identity algorithm used to derive seatId
   */
  seatIdAlgorithm: "seat-id-v1";
  /**
   * Canonical non-display identity key: Unicode NFC, namespace:opaque segments, no whitespace
   */
  identityKey: string;
  seatKind: SeatProfileSeatKind;
  canonicalName: string | null;
  /**
   * Inclusive business-validity start
   */
  validFrom: string;
  /**
   * Exclusive business-validity end; null means open-ended
   */
  validTo: string | null;
  availableTime: string;
  revisionId: string;
  previousRevisionId: string | null;
  source: string;
  sourceVersion: string;
  evidenceId: string;
  lineage: SeatLineage[];
}
export interface SeatLineage {
  lineageId: string;
  relation: SeatProfileLineageRelation;
  /**
   * @minItems 1
   */
  predecessorSeatIds: [string, ...string[]];
  /**
   * @minItems 1
   */
  successorSeatIds: [string, ...string[]];
  effectiveAt: string;
  source: string;
  sourceVersion: string;
  evidenceId: string;
  revisionId: string;
}

export type SeatTradeSchemaVersion = "seat-trade-v1";

/**
 * Immutable public Dragon-Tiger List fact, not a broker order or account transaction.
 */
export interface SeatTrade {
  schemaVersion: SeatTradeSchemaVersion;
  tradeId: string;
  revisionId: string;
  previousRevisionId: string | null;
  seatId: string;
  /**
   * Original source seat spelling preserved as evidence
   */
  rawSeatName: string;
  instrumentId: string;
  tradeDate: string;
  currency: "CNY";
  buyAmount: string;
  sellAmount: string;
  netAmount: string;
  source: string;
  sourceVersion: string;
  rawRecordId: string;
  evidenceId: string;
  availableTime: string;
}

/**
 * A point-in-time instrument membership interval with source version and evidence
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
  /**
   * Version of the source membership set
   */
  sourceVersion: string;
  /**
   * Earliest point-in-time availability
   */
  availableTime: string;
  /**
   * Immutable source evidence identifier
   */
  evidenceId: string;
}

/**
 * Versioned idempotent sector-rotation event with evidence-window provenance
 */
export interface SectorRotationEvent {
  eventId: string;
  date: string;
  eventType: "CROSSOVER" | "DECAY";
  fromSector: string | null;
  toSector: string;
  timestamp: string;
  confidence: number;
  evidenceStart: string;
  evidenceEnd: string;
  sampleSize: number;
  algorithmVersion: string;
  sourceVersions: string[];
  evidenceIds: string[];
}

/**
 * A point-in-time sector taxonomy record with hierarchy, aliases, validity and evidence provenance
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
   * Version of the source taxonomy
   */
  sourceVersion: string;
  /**
   * Earliest point-in-time availability
   */
  availableTime: string;
  /**
   * Immutable source evidence identifier
   */
  evidenceId: string;
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
