/** Shared domain types. Generated from packages/contracts/schemas/. DO NOT EDIT BY HAND. */
/**
 * Owner-scoped durable in-app research notifications and read receipts
 */
export interface InAppNotificationCenter {
  schemaVersion: "in-app-notification-center-v1";
  generatedAt: string;
  unreadCount: number;
  /**
   * @maxItems 100
   */
  notifications: InAppNotification[];
  dataMeaning: "RESEARCH_IN_APP_ALERTS_NO_ORDER_PATH";
}
/**
 * This interface was referenced by `InAppNotificationCenter`'s JSON-Schema
 * via the `definition` "InAppNotification".
 */
export interface InAppNotification {
  schemaVersion: "in-app-notification-v1";
  notificationId: string;
  historyId: string;
  ruleId: string;
  instrumentId: string;
  title: string;
  body: string;
  availableAt: string;
  deliveryStatus: "PENDING" | "DELIVERED" | "FAILED";
  deliveryAttempts: number;
  readAt: string | null;
}

/**
 * Bounded evaluation summary for latest persisted daily market bars
 */
export interface WatchlistAlertEvaluationRun {
  schemaVersion: "watchlist-alert-evaluation-run-v1";
  generatedAt: string;
  rulesScanned: number;
  evaluated: number;
  skippedUnsupported: number;
  skippedNoData: number;
  failed: number;
  dataMeaning: "RESEARCH_ALERT_EVALUATION_NO_ORDER_PATH";
}

/**
 * This interface was referenced by `WatchlistAlertsWorkspace`'s JSON-Schema
 * via the `definition` "WatchlistAlertField".
 */
export type WatchlistAlertField =
  "LAST_PRICE" | "CHANGE_BPS" | "EMOTION_SCORE_BPS" | "FEATURE_VALUE";
/**
 * This interface was referenced by `WatchlistAlertsWorkspace`'s JSON-Schema
 * via the `definition` "WatchlistAlertOperator".
 */
export type WatchlistAlertOperator = "GT" | "GTE" | "LT" | "LTE" | "EQ";

/**
 * Versioned watchlist rules and durable in-app alert history
 */
export interface WatchlistAlertsWorkspace {
  schemaVersion: "watchlist-alerts-workspace-v1";
  ruleLanguage: "BOUNDED_COMPARISON_V1";
  generatedAt: string;
  rules: WatchlistAlertRule[];
  history: WatchlistAlertHistory[];
  supportedFields: WatchlistAlertField[];
  supportedOperators: WatchlistAlertOperator[];
  dataMeaning: "RESEARCH_ALERTS_ONLY_NO_ORDER_PATH";
}
/**
 * This interface was referenced by `WatchlistAlertsWorkspace`'s JSON-Schema
 * via the `definition` "WatchlistAlertRule".
 */
export interface WatchlistAlertRule {
  schemaVersion: "watchlist-alert-rule-v1";
  ruleId: string;
  revisionId: string;
  revision: number;
  name: string;
  enabled: boolean;
  /**
   * @minItems 1
   * @maxItems 100
   */
  instrumentIds: [string, ...string[]];
  condition: WatchlistAlertCondition;
  quietPeriod: WatchlistAlertQuietPeriod | null;
  throttleSeconds: number;
  notificationChannel: "IN_APP";
  createdAt: string;
  availableAt: string;
  previousRevisionId: string | null;
}
/**
 * This interface was referenced by `WatchlistAlertsWorkspace`'s JSON-Schema
 * via the `definition` "WatchlistAlertCondition".
 */
export interface WatchlistAlertCondition {
  field: WatchlistAlertField;
  operator: WatchlistAlertOperator;
  threshold: string;
  featureName: string | null;
}
/**
 * This interface was referenced by `WatchlistAlertsWorkspace`'s JSON-Schema
 * via the `definition` "WatchlistAlertQuietPeriod".
 */
export interface WatchlistAlertQuietPeriod {
  timezone: "Asia/Shanghai";
  startMinute: number;
  endMinute: number;
}
/**
 * This interface was referenced by `WatchlistAlertsWorkspace`'s JSON-Schema
 * via the `definition` "WatchlistAlertHistory".
 */
export interface WatchlistAlertHistory {
  schemaVersion: "watchlist-alert-history-v1";
  historyId: string;
  ruleId: string;
  revisionId: string;
  eventId: string;
  instrumentId: string;
  eventTime: string;
  availableTime: string;
  outcome: "TRIGGERED" | "CONDITION_NOT_MET" | "THROTTLED" | "QUIET_PERIOD" | "RULE_DISABLED";
  observedValue: string | null;
  notificationId: string | null;
  notificationStatus: "NONE" | "PENDING" | "DELIVERED" | "FAILED";
  detail: string;
  createdAt: string;
}

/**
 * Active local research-terminal sessions represented by non-credential references
 */
export interface AuthSessionListResponse {
  schemaVersion: "auth-session-list-v1";
  generatedAt: string;
  /**
   * @maxItems 64
   */
  sessions: AuthSessionSummary[];
}
/**
 * This interface was referenced by `AuthSessionListResponse`'s JSON-Schema
 * via the `definition` "AuthSessionSummary".
 */
export interface AuthSessionSummary {
  sessionId: string;
  current: boolean;
  createdAt: string;
  lastSeenAt: string;
  idleExpiresAt: string;
  absoluteExpiresAt: string;
}
/**
 * This interface was referenced by `AuthSessionListResponse`'s JSON-Schema
 * via the `definition` "AuthPasswordChangeResponse".
 */
export interface AuthPasswordChangeResponse {
  schemaVersion: "auth-password-change-v1";
  changedAt: string;
  revokedOtherSessions: number;
}
/**
 * This interface was referenced by `AuthSessionListResponse`'s JSON-Schema
 * via the `definition` "AuthSessionRevocationResponse".
 */
export interface AuthSessionRevocationResponse {
  schemaVersion: "auth-session-revocation-v1";
  revoked: true;
}

/**
 * Authenticated local research-terminal session; no broker or real-order authority
 */
export interface AuthSessionResponse {
  schemaVersion: "auth-session-v1";
  authenticated: true;
  user: AuthUser;
  csrfToken: string;
  absoluteExpiresAt: string;
  idleExpiresAt: string;
}
/**
 * This interface was referenced by `AuthSessionResponse`'s JSON-Schema
 * via the `definition` "AuthUser".
 */
export interface AuthUser {
  userId: string;
  username: string;
  displayName: string;
  /**
   * @minItems 1
   * @maxItems 1
   */
  roles: ["platform_admin"];
}

/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "SafeId".
 */
export type SafeId = string;
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "DigestReference".
 */
export type DigestReference = ContentDigestReference | OpaqueExternalDigestReference;
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "Sha256".
 */
export type Sha256 = string;
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "Timestamp".
 */
export type Timestamp = string;
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "Decimal".
 */
export type Decimal = string;

export interface BacktestRegressionArtifact {
  schemaVersion: "backtest-regression-run-v1";
  canonicalizationVersion: "backtest-regression-c14n-v1";
  suiteId: SafeId;
  runId: SafeId;
  fixtureId: SafeId;
  trust: RegressionTrust;
  manifest: RegressionManifest;
  inputs: RegressionInputs;
  provenance: RegressionProvenance;
  versions: RegressionVersions;
  results: RegressionResults;
  artifactSha256: Sha256;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "RegressionTrust".
 */
export interface RegressionTrust {
  mode: "FIXTURE_SELF_CONTAINED" | "VERIFIED";
  evidenceIntegrityConfidence: "LOW" | "MEDIUM" | "HIGH";
  evidenceRefs: DigestReference[];
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "ContentDigestReference".
 */
export interface ContentDigestReference {
  kind: "CONTENT_SHA256";
  sha256: Sha256;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "OpaqueExternalDigestReference".
 */
export interface OpaqueExternalDigestReference {
  kind: "OPAQUE_EXTERNAL";
  namespace: string;
  value: string;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "RegressionManifest".
 */
export interface RegressionManifest {
  json: {
    [k: string]: unknown;
  };
  sha256: Sha256;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "RegressionInputs".
 */
export interface RegressionInputs {
  fixtureSha256: Sha256;
  executionInputDigests: Sha256[];
  portfolioHistoryRef: PortfolioHistoryRef;
  valuationLineage: ValuationLineage;
  /**
   * @minItems 4
   */
  navObservations: [Observation, Observation, Observation, Observation, ...Observation[]];
  /**
   * @minItems 4
   */
  riskFreeObservations: [
    RiskFreeObservation,
    RiskFreeObservation,
    RiskFreeObservation,
    RiskFreeObservation,
    ...RiskFreeObservation[],
  ];
  tPlusOne: TPlusOneInputs;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "PortfolioHistoryRef".
 */
export interface PortfolioHistoryRef {
  tapeId: SafeId;
  eventTapeDigest: Sha256;
  eventCount: number;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "ValuationLineage".
 */
export interface ValuationLineage {
  valuationPolicyId: string;
  valuationPolicyVersion: string;
  valuationPolicyDigest: Sha256;
  valuations: ValuationLineageItem[];
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "ValuationLineageItem".
 */
export interface ValuationLineageItem {
  observationTime: Timestamp;
  inputDigest: Sha256;
  markDigest: Sha256;
  stateDigest: Sha256;
  nav: Decimal;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "Observation".
 */
export interface Observation {
  observationTime: Timestamp;
  nav: Decimal;
  provenanceDigest: Sha256;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "RiskFreeObservation".
 */
export interface RiskFreeObservation {
  observationTime: Timestamp;
  rate: Decimal;
  provenanceDigest: Sha256;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "TPlusOneInputs".
 */
export interface TPlusOneInputs {
  buyOrderId: SafeId;
  sellOrderId: SafeId;
  buyExecutionInputDigest: Sha256;
  sameDaySellabilityDigest: Sha256;
  nextDaySellabilityDigest: Sha256;
  sameDayBatchDigest: Sha256;
  nextDayBatchDigest: Sha256;
  sameDaySellExecutionInputDigest: Sha256;
  nextDaySellExecutionInputDigest: Sha256;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "RegressionProvenance".
 */
export interface RegressionProvenance {
  code: CodeProvenance;
  config: DigestEntry[];
  dependencies: DigestEntry[];
  toolchain: ToolchainEvidence;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "CodeProvenance".
 */
export interface CodeProvenance {
  allowlist: CodeDigestEntry[];
  treeSha256: Sha256;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "CodeDigestEntry".
 */
export interface CodeDigestEntry {
  path: string;
  sha256: Sha256;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "DigestEntry".
 */
export interface DigestEntry {
  name: string;
  version: string;
  sha256: Sha256;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "ToolchainEvidence".
 */
export interface ToolchainEvidence {
  python: "3.12.13";
  uv: "0.12.3";
  evidenceSha256: Sha256;
  hatchling: string;
  rootPyprojectSha256: Sha256;
  servicePyprojectSha256: Sha256;
  uvLockSha256: Sha256;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "RegressionVersions".
 */
export interface RegressionVersions {
  engine: string;
  manifest: string;
  eventOrder: string;
  execution: string;
  matching: string;
  portfolio: string;
  valuation: string;
  metrics: string;
  strategy: string;
  policy: string;
  fixture: string;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "RegressionResults".
 */
export interface RegressionResults {
  counts: {
    events: number;
    intents: number;
    orders: number;
    fills: number;
    navObservations: number;
    tPlusOneRejected: number;
    nextDaySellFills: number;
  };
  pnl: {
    realized: Decimal;
    unrealized: Decimal;
    total: Decimal;
    fees: Decimal;
  };
  finalNav: Decimal;
  finalValuation: FinalValuation;
  metrics: {
    cumulativeChainedReturn: MetricValue;
    annualizedReturn: MetricValue;
    annualizedVolatility: MetricValue;
    maximumDrawdown: MetricValue;
    sharpe: MetricValue;
    sortino: MetricValue;
    calmar: MetricValue;
  };
  /**
   * @minItems 4
   */
  observations: [Observation, Observation, Observation, Observation, ...Observation[]];
  tPlusOne: TPlusOneResults;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "FinalValuation".
 */
export interface FinalValuation {
  cutoffTime: Timestamp;
  nav: Decimal;
  totalPnl: Decimal;
  stateDigest: Sha256;
  inputDigest: Sha256;
  sampleCount: number;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "MetricValue".
 */
export interface MetricValue {
  status: string;
  value: string | null;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "TPlusOneResults".
 */
export interface TPlusOneResults {
  sameDay: TPlusOneObservation;
  nextDay: TPlusOneObservation;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "TPlusOneObservation".
 */
export interface TPlusOneObservation {
  orderId: SafeId;
  status: "REJECTED" | "FILLED";
  rejectReason: string | null;
  fillCount: number;
  batchDigest: Sha256;
  resultDigest: Sha256;
  tradingDate: string;
  sellabilityDigest: Sha256 | null;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "CategoryCounts".
 */
export interface CategoryCounts {
  SCHEMA: number;
  MANIFEST_INPUT: number;
  ALGORITHM_CONFIG: number;
  DEPENDENCY_TOOLCHAIN: number;
  RESULT: number;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "ZeroCategoryCounts".
 */
export interface ZeroCategoryCounts {
  SCHEMA: 0;
  MANIFEST_INPUT: 0;
  ALGORITHM_CONFIG: 0;
  DEPENDENCY_TOOLCHAIN: 0;
  RESULT: 0;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "BaselineApproval".
 */
export interface BaselineApproval {
  approvalId: SafeId;
  reviewedBy: string;
  reviewedAt: Timestamp;
  reviewedArtifactSha256: Sha256;
  changeReference: DigestReference;
  reason: string;
  evidenceRefs: DigestReference[];
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "BacktestRegressionBaseline".
 */
export interface BacktestRegressionBaseline {
  schemaVersion: "backtest-regression-baseline-v1";
  baselineId: SafeId;
  suiteId: SafeId;
  expectedArtifact: BacktestRegressionArtifact;
  expectedArtifactSha256: Sha256;
  approval: BaselineApproval;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "BacktestRegressionRunSummary".
 */
export interface BacktestRegressionRunSummary {
  schemaVersion: "backtest-regression-summary-v1";
  suiteId: SafeId;
  runId: SafeId;
  fixtureId: SafeId;
  status: "MATCHED" | "DRIFTED";
  candidateSha256: Sha256;
  baselineSha256: Sha256;
  dataStart: Timestamp;
  dataEnd: Timestamp;
  availability: string;
  evidenceIntegrityConfidence: "LOW" | "MEDIUM" | "HIGH";
  preview: boolean;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "BacktestRegressionDiff".
 */
export interface BacktestRegressionDiff {
  category: "SCHEMA" | "MANIFEST_INPUT" | "ALGORITHM_CONFIG" | "DEPENDENCY_TOOLCHAIN" | "RESULT";
  pointer: string;
  status: "ADDED" | "REMOVED" | "REPLACED";
  baselineValue: unknown;
  candidateValue: unknown;
}
/**
 * This interface was referenced by `BacktestRegressionArtifact`'s JSON-Schema
 * via the `definition` "BacktestRegressionComparison".
 */
export interface BacktestRegressionComparison {
  baselineSha256: Sha256;
  candidateSha256: Sha256;
  status: "MATCHED" | "DRIFTED";
  categoryCounts: CategoryCounts;
  diffs: BacktestRegressionDiff[];
  diffLines: string[];
}

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
 * Fingerprint algorithm version
 *
 * This interface was referenced by `RawContent`'s JSON-Schema
 * via the `definition` "FingerprintVersion".
 */
export type FingerprintVersion = "sha256-v1";

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
 * Attribution of content to its source (id / version / evidence)
 *
 * This interface was referenced by `RawContent`'s JSON-Schema
 * via the `definition` "ContentSource".
 */
export interface ContentSource2 {
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
 * License and usage-restriction metadata; authorized must be explicit
 *
 * This interface was referenced by `RawContent`'s JSON-Schema
 * via the `definition` "LicenseMetadata".
 */
export interface LicenseMetadata1 {
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
 * This interface was referenced by `MarketCoverageResponse`'s JSON-Schema
 * via the `definition` "MarketCoverageSource".
 */
export type MarketCoverageSource =
  "tushare-pro" | "akshare-tencent" | "akshare-sina" | "akshare-eastmoney";

/**
 * Observed daily raw market-bar coverage; this is not a completeness or quality verdict.
 */
export interface MarketCoverageResponse {
  schemaVersion: "market-data-coverage-v1";
  scope: "DAILY_RAW_SUPPORTED_SOURCES";
  meaning: "OBSERVED_ONLY";
  window: MarketCoverageWindow;
  /**
   * @maxItems 100
   */
  rows: MarketCoverageRow[];
  truncated: boolean;
}
/**
 * This interface was referenced by `MarketCoverageResponse`'s JSON-Schema
 * via the `definition` "MarketCoverageWindow".
 */
export interface MarketCoverageWindow {
  dateFrom: string;
  dateTo: string;
  asOf: string;
}
/**
 * This interface was referenced by `MarketCoverageResponse`'s JSON-Schema
 * via the `definition` "MarketCoverageRow".
 */
export interface MarketCoverageRow {
  unifiedCode: string;
  source: MarketCoverageSource;
  observedBarDays: number;
  firstDate: string;
  lastDate: string;
  latestEventTime: string;
  latestAvailableTime: string;
  latestProcessingTime: string;
}

/**
 * This interface was referenced by `MarketQualityEvidencePage`'s JSON-Schema
 * via the `definition` "MarketQualitySource".
 */
export type MarketQualitySource =
  "tushare-pro" | "akshare-tencent" | "akshare-sina" | "akshare-eastmoney";
/**
 * This interface was referenced by `MarketQualityEvidencePage`'s JSON-Schema
 * via the `definition` "MarketQualityInterval".
 */
export type MarketQualityInterval = "DAILY" | "MINUTE_1" | "MINUTE_5";
/**
 * This interface was referenced by `MarketQualityEvidencePage`'s JSON-Schema
 * via the `definition` "MarketQualityStatus".
 */
export type MarketQualityStatus = "REJECTED" | "FILTERED";
/**
 * This interface was referenced by `MarketQualityEvidencePage`'s JSON-Schema
 * via the `definition` "MarketQualityReasonCode".
 */
export type MarketQualityReasonCode =
  "PROVIDER_PARSE_ERROR" | "BAR_QUALITY_REJECTED" | "SINA_OVERFETCH_OUTSIDE_REQUEST";
/**
 * This interface was referenced by `MarketQualityEvidencePage`'s JSON-Schema
 * via the `definition` "MarketQualityKind".
 */
export type MarketQualityKind =
  "OUT_OF_ORDER" | "DUPLICATE" | "NEGATIVE_PRICE" | "ABNORMAL_VOLUME" | "MISSING_FIELD";
/**
 * This interface was referenced by `MarketQualityEvidencePage`'s JSON-Schema
 * via the `definition` "MarketQualityFilteredReasonCode".
 */
export type MarketQualityFilteredReasonCode = "SINA_OVERFETCH_OUTSIDE_REQUEST";

/**
 * A bounded, sanitized page of market-data rejection and filtering evidence.
 */
export interface MarketQualityEvidencePage {
  schemaVersion: "market-quality-evidence-v1";
  snapshotId: string;
  publishedAt: string;
  snapshotRecordCount: number;
  matchingRecordCount: number;
  offset: number;
  limit: number;
  hasMore: boolean;
  /**
   * @maxItems 100
   */
  records: MarketQualityEvidenceRecord[];
}
/**
 * This interface was referenced by `MarketQualityEvidencePage`'s JSON-Schema
 * via the `definition` "MarketQualityEvidenceRecord".
 */
export interface MarketQualityEvidenceRecord {
  evidenceId: string;
  source: MarketQualitySource;
  unifiedCode: string;
  interval: MarketQualityInterval;
  requestedStart: string;
  requestedEnd: string;
  status: MarketQualityStatus;
  reasonCode: MarketQualityReasonCode;
  captureAvailableAt: string;
  qualityRecordedAt: string;
  rejectedRecordCount: number;
  qualityEventCount: number;
  filteredRecordCount: number;
  /**
   * @maxItems 10000
   */
  qualityEvents: MarketQualityEvent[];
  /**
   * @maxItems 10000
   */
  filteredRecords: MarketQualityFilteredRecord[];
}
/**
 * This interface was referenced by `MarketQualityEvidencePage`'s JSON-Schema
 * via the `definition` "MarketQualityEvent".
 */
export interface MarketQualityEvent {
  kind: MarketQualityKind;
  unifiedCode: string | null;
  timestamp: string | null;
}
/**
 * This interface was referenced by `MarketQualityEvidencePage`'s JSON-Schema
 * via the `definition` "MarketQualityFilteredRecord".
 */
export interface MarketQualityFilteredRecord {
  rawRowIndex: number;
  timestamp: string;
  requestedStart: string;
  requestedEnd: string;
  reasonCode: MarketQualityFilteredReasonCode;
}
/**
 * Immutable storage snapshot; its filename is the SHA-256 of canonical JSON bytes.
 *
 * This interface was referenced by `MarketQualityEvidencePage`'s JSON-Schema
 * via the `definition` "MarketQualityEvidenceSnapshot".
 */
export interface MarketQualityEvidenceSnapshot {
  schemaVersion: "market-quality-snapshot-v1";
  publishedAt: string;
  /**
   * @maxItems 10000
   */
  records: MarketQualityEvidenceRecord[];
}
/**
 * Atomic pointer to one complete immutable market-quality snapshot.
 *
 * This interface was referenced by `MarketQualityEvidencePage`'s JSON-Schema
 * via the `definition` "MarketQualityEvidenceCurrent".
 */
export interface MarketQualityEvidenceCurrent {
  schemaVersion: "market-quality-current-v1";
  snapshotId: string;
}
/**
 * This interface was referenced by `MarketQualityEvidencePage`'s JSON-Schema
 * via the `definition` "MarketQualityEvidenceDetail".
 */
export interface MarketQualityEvidenceDetail {
  schemaVersion: "market-quality-evidence-v1";
  snapshotId: string;
  publishedAt: string;
  record: MarketQualityEvidenceRecord;
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

/**
 * This interface was referenced by `LimitPoolTerminalSnapshot`'s JSON-Schema
 * via the `definition` "NullableTimestamp".
 */
export type NullableTimestamp = string | null;
/**
 * This interface was referenced by `LimitPoolTerminalSnapshot`'s JSON-Schema
 * via the `definition` "LimitPoolTerminalCompleteness".
 */
export type LimitPoolTerminalCompleteness = "COMPLETE" | "PARTIAL" | "EMPTY";
/**
 * This interface was referenced by `LimitPoolTerminalSnapshot`'s JSON-Schema
 * via the `definition` "LimitPoolTerminalFreshnessStatus".
 */
export type LimitPoolTerminalFreshnessStatus =
  "FRESH" | "DELAYED" | "STALE" | "HISTORICAL" | "NO_DATA";
/**
 * This interface was referenced by `LimitPoolTerminalSnapshot`'s JSON-Schema
 * via the `definition` "NullableVersion".
 */
export type NullableVersion = string | null;
/**
 * This interface was referenced by `LimitPoolTerminalSnapshot`'s JSON-Schema
 * via the `definition` "LimitPoolListingBoard".
 */
export type LimitPoolListingBoard = "MAIN" | "CHINEXT" | "STAR" | "BSE";
/**
 * This interface was referenced by `LimitPoolTerminalSnapshot`'s JSON-Schema
 * via the `definition` "LimitPoolSide".
 */
export type LimitPoolSide = "LIMIT_UP" | "LIMIT_DOWN";
/**
 * This interface was referenced by `LimitPoolTerminalSnapshot`'s JSON-Schema
 * via the `definition` "LimitPoolState".
 */
export type LimitPoolState = "SEALED" | "OPENED" | "LIMIT_DOWN";
/**
 * Canonical finite decimal string strictly greater than zero
 *
 * This interface was referenced by `LimitPoolTerminalSnapshot`'s JSON-Schema
 * via the `definition` "PositiveDecimalString".
 */
export type PositiveDecimalString = string;

/**
 * Versioned point-in-time projection consumed by the limit-pool terminal
 */
export interface LimitPoolTerminalSnapshot {
  schemaVersion: "limit-pool-terminal-v1";
  mode: "CURRENT" | "HISTORICAL";
  requestedAsOf: string;
  tradingDate: string | null;
  previousTradingDate: string | null;
  dataCutoffTime: NullableTimestamp;
  availableTime: NullableTimestamp;
  completeness: LimitPoolTerminalCompleteness;
  missingReasons: string[];
  freshness: {
    status: LimitPoolTerminalFreshnessStatus;
    ageSeconds: number | null;
  };
  algorithmVersion: NullableVersion;
  ladderAlgorithmVersion: NullableVersion;
  limitRuleVersion: NullableVersion;
  materializerVersion: NullableVersion;
  revision: number | null;
  limitUpCount: number;
  limitDownCount: number;
  sealedCount: number;
  totalOpenCount: number;
  ladder: LimitPoolLadderLevel[];
  entries: LimitPoolTerminalEntry[];
  sourceVersions: string[];
  evidenceIds: string[];
  dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH";
}
/**
 * This interface was referenced by `LimitPoolTerminalSnapshot`'s JSON-Schema
 * via the `definition` "LimitPoolLadderLevel".
 */
export interface LimitPoolLadderLevel {
  streakDays: number;
  count: number;
  previousDayEligibleCount: number;
  promotedCount: number;
  promotionRateBps: number | null;
  algorithmVersion: string;
}
/**
 * One auditable instrument row emitted by the versioned limit-pool algorithm
 *
 * This interface was referenced by `LimitPoolTerminalSnapshot`'s JSON-Schema
 * via the `definition` "LimitPoolTerminalEntry".
 */
export interface LimitPoolTerminalEntry {
  instrumentId: string;
  name: string;
  exchange: "SH" | "SZ" | "BJ";
  listingBoard: LimitPoolListingBoard;
  isSt: boolean;
  side: LimitPoolSide;
  state: LimitPoolState;
  streakDays: number;
  previousStreakDays: number;
  openCount: number;
  priceCny: PositiveDecimalString;
  previousCloseCny: PositiveDecimalString;
  firstSealTime: NullableTimestamp;
  lastSealTime: NullableTimestamp;
  eventTime: string;
  availableTime: string;
  revision: number;
  sourceVersion: string;
  evidenceId: string;
  algorithmVersion: string;
  ladderAlgorithmVersion: string;
  limitRuleVersion: string;
  materializerVersion: string;
  dataMeaning: "LIMIT_POOL_ALGORITHM_OUTPUT";
}

/**
 * This interface was referenced by `MarketOverviewSnapshot`'s JSON-Schema
 * via the `definition` "MarketOverviewFreshnessStatus".
 */
export type MarketOverviewFreshnessStatus =
  "FRESH" | "DELAYED" | "STALE" | "HISTORICAL" | "NO_DATA";

/**
 * Versioned point-in-time market dashboard projection
 */
export interface MarketOverviewSnapshot {
  schemaVersion: "market-overview-v1";
  mode: "CURRENT" | "HISTORICAL";
  requestedAsOf: string;
  dataCutoffTime: string | null;
  completeness: "COMPLETE" | "PARTIAL" | "EMPTY";
  freshness: {
    status: MarketOverviewFreshnessStatus;
    ageSeconds: number | null;
    delayedAfterSeconds: number;
    staleAfterSeconds: number;
  };
  indices: MarketOverviewIndexMetric[];
  breadth: MarketOverviewBreadthMetric | null;
  turnover: MarketOverviewTurnoverMetric | null;
  emotion: MarketOverviewEmotionMetric | null;
  risk: MarketOverviewRiskMetric;
  sourceVersions: string[];
  evidenceIds: string[];
  dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH";
}
/**
 * This interface was referenced by `MarketOverviewSnapshot`'s JSON-Schema
 * via the `definition` "MarketOverviewIndexMetric".
 */
export interface MarketOverviewIndexMetric {
  instrumentId: string;
  name: string;
  dataTime: string;
  value: string;
  previousClose: string;
  changeBps: number;
  sourceVersion: string;
  evidenceId: string;
}
/**
 * This interface was referenced by `MarketOverviewSnapshot`'s JSON-Schema
 * via the `definition` "MarketOverviewBreadthMetric".
 */
export interface MarketOverviewBreadthMetric {
  dataTime: string;
  advancingCount: number;
  decliningCount: number;
  unchangedCount: number;
  suspendedCount: number;
  sampleSize: number;
  advancingRatioBps: number;
  universeVersion: "ashare-code-pattern-v1";
  sourceVersions: string[];
  evidenceIds: string[];
}
/**
 * This interface was referenced by `MarketOverviewSnapshot`'s JSON-Schema
 * via the `definition` "MarketOverviewTurnoverMetric".
 */
export interface MarketOverviewTurnoverMetric {
  dataTime: string;
  amountCny: string;
  sampleSize: number;
  sourceVersions: string[];
  evidenceIds: string[];
}
/**
 * This interface was referenced by `MarketOverviewSnapshot`'s JSON-Schema
 * via the `definition` "MarketOverviewEmotionMetric".
 */
export interface MarketOverviewEmotionMetric {
  dataTime: string;
  scoreBps: number;
  confidenceBps: number;
  sampleSize: number;
  algorithmVersion: string;
  sourceVersions: string[];
  evidenceIds: string[];
}
/**
 * This interface was referenced by `MarketOverviewSnapshot`'s JSON-Schema
 * via the `definition` "MarketOverviewRiskMetric".
 */
export interface MarketOverviewRiskMetric {
  state: "CALM" | "WATCH" | "STRESSED" | "UNKNOWN";
  basisVersion: "market-risk-temperature-v1";
  explanation: string;
  dataMeaning: "RESEARCH_CONTEXT_NOT_ORDER_RISK";
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
/**
 * This interface was referenced by `EventFeedbackSubmission`'s JSON-Schema
 * via the `definition` "correction".
 */
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
/**
 * This interface was referenced by `EventFeedback`'s JSON-Schema
 * via the `definition` "correction".
 */
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

/**
 * This interface was referenced by `MarketEvent`'s JSON-Schema
 * via the `definition` "MarketEventType".
 */
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
/**
 * This interface was referenced by `MarketEvent`'s JSON-Schema
 * via the `definition` "ProducerType".
 */
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
/**
 * This interface was referenced by `MarketEvent`'s JSON-Schema
 * via the `definition` "EvidenceReference".
 */
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
/**
 * This interface was referenced by `MarketEvent`'s JSON-Schema
 * via the `definition` "ModelProvenance".
 */
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
 * Version 1 point-in-time benchmark reference observation; it is never an executable price
 */
export interface BenchmarkSeriesPoint {
  /**
   * Stable version of the benchmark-series point contract
   */
  schemaVersion: "benchmark-series-point-v1";
  /**
   * Canonical benchmark:v1:<namespace>:<key> identity; lowercase ASCII, not a label
   */
  benchmarkId: string;
  /**
   * ISO 4217 currency of the reference value
   */
  currency: string;
  /**
   * Explicit benchmark valuation/return basis
   */
  priceBasis: string;
  /**
   * Positive fixed-point decimal wire string; Python domain type is Decimal
   */
  referenceValue: string;
  /**
   * Economic observation/event time (timezone required)
   */
  eventTime: string;
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
   * Data source provenance identifier
   */
  source: string;
  /**
   * Source revision or vendor version for this observation
   */
  sourceRevision: string;
  /**
   * Immutable raw evidence/object identifier
   */
  rawObjectId: string;
  /**
   * SHA-256 digest of the canonical source payload
   */
  payloadDigest: string;
  /**
   * Reference-only marker; true is mandatory and cannot imply execution
   */
  referenceOnly: true;
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
   * Optional canonical benchmark:v1:<namespace>:<key> identity; null means unavailable
   */
  benchmarkSeriesId?: string | null;
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
 * Point-in-time read model for exchange-listed precious-metals funds; NAV and iNAV are non-executable reference values
 */
export interface PreciousMetalsTerminalSnapshot {
  schemaVersion: "precious-metals-terminal-v1";
  mode: "CURRENT" | "HISTORICAL";
  requestedAsOf: string;
  effectiveAsOf: string;
  generatedAt: string;
  status: "AVAILABLE" | "PARTIAL" | "EMPTY" | "UNAVAILABLE";
  executionCapability: "REFERENCE_ONLY";
  valuationPolicy: "NAV_INAV_NON_EXECUTABLE";
  rankingAlgorithmVersion: "precious-metals-turnover-ranking-v1";
  rankingMetric: "LATEST_EXCHANGE_TURNOVER_CNY";
  sampleSize: number;
  gaps: PreciousMetalsTerminalGap[];
  sourceVersions: string[];
  evidenceIds: string[];
  funds: PreciousMetalsTerminalFund[];
  events: PreciousMetalsTerminalEvent[];
}
/**
 * This interface was referenced by `PreciousMetalsTerminalSnapshot`'s JSON-Schema
 * via the `definition` "PreciousMetalsTerminalGap".
 */
export interface PreciousMetalsTerminalGap {
  scope: "METADATA" | "MARKET" | "NAV" | "INAV" | "FEATURES" | "EVENTS";
  severity: "INFO" | "WARNING" | "ERROR";
  code:
    "SOURCE_UNAVAILABLE" | "NO_VISIBLE_DATA" | "STALE_DATA" | "INVALID_UPSTREAM_DATA" | "TRUNCATED";
  instrumentId: string | null;
  message: string;
}
/**
 * This interface was referenced by `PreciousMetalsTerminalSnapshot`'s JSON-Schema
 * via the `definition` "PreciousMetalsTerminalFund".
 */
export interface PreciousMetalsTerminalFund {
  unifiedCode: string;
  displayName: string;
  exchange: "SH" | "SZ" | "BJ";
  assetType: "ETF" | "LOF" | "FUND";
  underlyingCommodity: "GOLD" | "SILVER" | "OTHER";
  tradingCurrency: "CNY";
  navCurrency: string;
  benchmarkOrTrackingIndex: string;
  managementFeeRateBps: number;
  metadataConfidenceBps: number;
  reviewStatus: "REVIEWED" | "NEEDS_REVIEW";
  metadataSource: string;
  metadataSourceVersion: string;
  metadataAvailableTime: string;
  metadataProcessingTime: string;
  market: PreciousMetalsTerminalMarket | null;
  valuation: PreciousMetalsTerminalValuation;
  features: PreciousMetalsTerminalFeature[];
  ranking: PreciousMetalsTerminalRanking | null;
  alertContext: PreciousMetalsTerminalAlertContext;
}
/**
 * This interface was referenced by `PreciousMetalsTerminalSnapshot`'s JSON-Schema
 * via the `definition` "PreciousMetalsTerminalMarket".
 */
export interface PreciousMetalsTerminalMarket {
  date: string;
  eventTime: string;
  close: string;
  volume: string;
  turnoverCny: string;
  suspended: boolean;
  freshness: "FRESH" | "STALE";
  source: string;
  sourceVersion: string;
  dataVersion: string;
  availableTime: string;
  processingTime: string;
  evidenceId: string;
}
/**
 * This interface was referenced by `PreciousMetalsTerminalSnapshot`'s JSON-Schema
 * via the `definition` "PreciousMetalsTerminalValuation".
 */
export interface PreciousMetalsTerminalValuation {
  navValue: string | null;
  inavValue: string | null;
  referenceKind: "NAV" | "INAV" | null;
  referenceValue: string | null;
  referenceDate: string | null;
  premiumDiscountBps: string | null;
  freshness: "FRESH" | "STALE" | "MISSING";
  staleAfterSeconds: number | null;
  source: string | null;
  sourceVersion: string | null;
  availableTime: string | null;
  processingTime: string | null;
  evidenceIds: string[];
  referenceOnly: true;
}
/**
 * This interface was referenced by `PreciousMetalsTerminalSnapshot`'s JSON-Schema
 * via the `definition` "PreciousMetalsTerminalFeature".
 */
export interface PreciousMetalsTerminalFeature {
  name: string;
  value: string;
  valueType: "BOOLEAN" | "INTEGER" | "DECIMAL" | "STRING" | "CATEGORY";
  featureVersion: string;
  algorithmVersion: string;
  eventTime: string;
  availableTime: string;
  processingTime: string;
  evidenceId: string;
}
/**
 * This interface was referenced by `PreciousMetalsTerminalSnapshot`'s JSON-Schema
 * via the `definition` "PreciousMetalsTerminalRanking".
 */
export interface PreciousMetalsTerminalRanking {
  rank: number;
  metric: "LATEST_EXCHANGE_TURNOVER_CNY";
  metricValue: string;
  algorithmVersion: "precious-metals-turnover-ranking-v1";
  sampleSize: number;
  confidenceBps: number;
}
/**
 * This interface was referenced by `PreciousMetalsTerminalSnapshot`'s JSON-Schema
 * via the `definition` "PreciousMetalsTerminalAlertContext".
 */
export interface PreciousMetalsTerminalAlertContext {
  instrumentId: string;
  /**
   * @minItems 2
   * @maxItems 2
   */
  supportedFields: ["LAST_PRICE" | "FEATURE_VALUE", "LAST_PRICE" | "FEATURE_VALUE"];
  premiumFeatureName: "precious_metals_fund.premium_discount_bps";
}
/**
 * This interface was referenced by `PreciousMetalsTerminalSnapshot`'s JSON-Schema
 * via the `definition` "PreciousMetalsTerminalEvent".
 */
export interface PreciousMetalsTerminalEvent {
  eventId: string;
  /**
   * @minItems 1
   */
  instrumentIds: [string, ...string[]];
  eventType: string;
  headline: string;
  summary: string;
  publishTime: string;
  availableTime: string;
  confidenceBps: number;
  modelVersion: string;
  /**
   * @minItems 1
   */
  evidenceIds: [string, ...string[]];
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
 * Versioned point-in-time daily RAW bars for research display; no real-order capability
 */
export interface InstrumentBarsResponse {
  schemaVersion: "instrument-bars-v1";
  dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH";
  instrumentId: string;
  mode: "CURRENT" | "HISTORICAL";
  requestedAsOf: string;
  effectiveAsOf: string;
  interval: "DAILY";
  priceType: "RAW";
  status: "AVAILABLE" | "EMPTY";
  barCount: number;
  /**
   * Latest visible event time represented by the returned bars
   */
  dataCutoffTime: string | null;
  freshnessSeconds: number | null;
  /**
   * @maxItems 500
   */
  bars: InstrumentDailyBar[];
  sourceVersions: string[];
  evidenceIds: string[];
}
/**
 * This interface was referenced by `InstrumentBarsResponse`'s JSON-Schema
 * via the `definition` "InstrumentDailyBar".
 */
export interface InstrumentDailyBar {
  date: string;
  eventTime: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
  amount: string;
  suspended: boolean;
  availableTime: string;
  processingTime: string;
  source: string;
  sourceVersion: string;
  dataVersion: string;
  evidenceId: string;
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
 * This interface was referenced by `InstrumentIntelligenceDetail`'s JSON-Schema
 * via the `definition` "IdentitySection".
 */
export type IdentitySection = SectionMetadata & {
  data: Identity | null;
  [k: string]: unknown;
};
/**
 * This interface was referenced by `InstrumentIntelligenceDetail`'s JSON-Schema
 * via the `definition` "MarketSection".
 */
export type MarketSection = SectionMetadata & {
  data: MarketBar | null;
  [k: string]: unknown;
};
/**
 * This interface was referenced by `InstrumentIntelligenceDetail`'s JSON-Schema
 * via the `definition` "EmotionSection".
 */
export type EmotionSection = SectionMetadata & {
  data: Emotion | null;
  [k: string]: unknown;
};
/**
 * This interface was referenced by `InstrumentIntelligenceDetail`'s JSON-Schema
 * via the `definition` "SectorSection".
 */
export type SectorSection = SectionMetadata & {
  data: SectorItem[];
  [k: string]: unknown;
};
/**
 * This interface was referenced by `InstrumentIntelligenceDetail`'s JSON-Schema
 * via the `definition` "EventSection".
 */
export type EventSection = SectionMetadata & {
  data: EventItem[];
  [k: string]: unknown;
};
/**
 * This interface was referenced by `InstrumentIntelligenceDetail`'s JSON-Schema
 * via the `definition` "SeatSection".
 */
export type SeatSection = SectionMetadata & {
  data: SeatItem[];
  [k: string]: unknown;
};
/**
 * This interface was referenced by `InstrumentIntelligenceDetail`'s JSON-Schema
 * via the `definition` "KolClaimSection".
 */
export type KolClaimSection = SectionMetadata & {
  data: KolClaimItem[];
  [k: string]: unknown;
};
/**
 * This interface was referenced by `InstrumentIntelligenceDetail`'s JSON-Schema
 * via the `definition` "FeatureSection".
 */
export type FeatureSection = SectionMetadata & {
  data: FeatureItem[];
  [k: string]: unknown;
};

/**
 * Research-only point-in-time instrument intelligence assembled across PostgreSQL and ClickHouse without any execution capability.
 */
export interface InstrumentIntelligenceDetail {
  schemaVersion: "instrument-intelligence-detail-v1";
  dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH";
  instrumentId: string;
  mode: "CURRENT" | "HISTORICAL";
  requestedAsOf: string;
  effectiveAsOf: string;
  generatedAt: string;
  snapshotBoundary: SnapshotBoundary;
  sections: Sections;
  evidence: EvidenceLink[];
}
/**
 * This interface was referenced by `InstrumentIntelligenceDetail`'s JSON-Schema
 * via the `definition` "SnapshotBoundary".
 */
export interface SnapshotBoundary {
  consistency: "BEST_EFFORT_CROSS_STORE";
  postgresIsolation: "REPEATABLE_READ";
  effectiveAsOf: string;
  /**
   * @minItems 2
   * @maxItems 2
   */
  stores: ["POSTGRESQL" | "CLICKHOUSE", "POSTGRESQL" | "CLICKHOUSE"];
}
/**
 * This interface was referenced by `InstrumentIntelligenceDetail`'s JSON-Schema
 * via the `definition` "Sections".
 */
export interface Sections {
  identity: IdentitySection;
  market: MarketSection;
  emotion: EmotionSection;
  sector: SectorSection;
  events: EventSection;
  seats: SeatSection;
  kolClaims: KolClaimSection;
  features: FeatureSection;
}
/**
 * This interface was referenced by `InstrumentIntelligenceDetail`'s JSON-Schema
 * via the `definition` "SectionMetadata".
 */
export interface SectionMetadata {
  status: "AVAILABLE" | "EMPTY" | "UNAVAILABLE";
  requestedAsOf: string;
  effectiveAsOf: string;
  dataCutoffTime: string | null;
  availableTime: string | null;
  processingTime: string | null;
  freshnessSeconds: number | null;
  unavailableReason: string | null;
  sourceVersions: string[];
  evidenceIds: string[];
}
/**
 * This interface was referenced by `InstrumentIntelligenceDetail`'s JSON-Schema
 * via the `definition` "Identity".
 */
export interface Identity {
  unifiedCode: string;
  code: string;
  exchange: "SH" | "SZ" | "BJ";
  board: "MAIN" | "CHINEXT" | "STAR" | "BSE";
  type: "STOCK" | "ETF" | "LOF" | "FUND";
  name: string;
  tradingStatus: "LISTED" | "SUSPENDED" | "ST" | "DELISTED";
  currency: "CNY";
  listDate: string | null;
  delistDate: string | null;
}
/**
 * This interface was referenced by `InstrumentIntelligenceDetail`'s JSON-Schema
 * via the `definition` "MarketBar".
 */
export interface MarketBar {
  date: string;
  eventTime: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
  amount: string;
  suspended: boolean;
  dataVersion: string;
  source: string;
  sourceVersion: string;
  evidenceId: string;
  availableTime: string;
  processingTime: string;
}
/**
 * This interface was referenced by `InstrumentIntelligenceDetail`'s JSON-Schema
 * via the `definition` "Emotion".
 */
export interface Emotion {
  eventTime: string;
  score: string;
  confidenceBps: number;
  sampleSize: number;
  algorithmVersion: string;
  availableTime: string;
  processingTime: string;
}
/**
 * This interface was referenced by `InstrumentIntelligenceDetail`'s JSON-Schema
 * via the `definition` "SectorItem".
 */
export interface SectorItem {
  sectorId: string;
  name: string;
  kind: "INDUSTRY" | "CONCEPT" | "THEME";
  validFrom: string;
  validTo: string | null;
  source: string;
  sourceVersion: string;
  availableTime: string;
  evidenceId: string;
}
/**
 * This interface was referenced by `InstrumentIntelligenceDetail`'s JSON-Schema
 * via the `definition` "EventItem".
 */
export interface EventItem {
  eventId: string;
  eventType: string;
  headline: string;
  summary: string;
  occurTime: string;
  publishTime: string;
  availableTime: string;
  confidenceBps: number;
  modelVersion: string;
  evidenceIds: string[];
}
/**
 * This interface was referenced by `InstrumentIntelligenceDetail`'s JSON-Schema
 * via the `definition` "SeatItem".
 */
export interface SeatItem {
  tradeId: string;
  revisionId: string;
  seatId: string;
  rawSeatName: string;
  tradeDate: string;
  currency: "CNY";
  buyAmount: string;
  sellAmount: string;
  netAmount: string;
  availableTime: string;
  evidenceId: string;
  dataMeaning: "PUBLIC_DRAGON_TIGER_FACT_NOT_BROKER_ORDER";
}
/**
 * This interface was referenced by `InstrumentIntelligenceDetail`'s JSON-Schema
 * via the `definition` "KolClaimItem".
 */
export interface KolClaimItem {
  claimId: string;
  revisionId: string;
  kolId: string;
  statement: string;
  direction: string;
  reviewStatus: "UNREVIEWED" | "IN_REVIEW" | "APPROVED" | "REJECTED";
  confidenceBps: number;
  publishTime: string;
  availableTime: string;
  evidenceIds: string[];
  claimMeaning: "PUBLIC_WORDING_CLAIM_NOT_BROKER_TRADE";
}
/**
 * This interface was referenced by `InstrumentIntelligenceDetail`'s JSON-Schema
 * via the `definition` "FeatureItem".
 */
export interface FeatureItem {
  featureName: string;
  featureVersion: string;
  featureFingerprint: string;
  algorithmVersion: string;
  valueType: string;
  value: unknown;
  eventTime: string;
  availableTime: string;
  processingTime: string;
  lineageChecksum: string;
  sourceKind: string;
  sourceSnapshotVersion: string;
  revisionId: string;
}
/**
 * This interface was referenced by `InstrumentIntelligenceDetail`'s JSON-Schema
 * via the `definition` "EvidenceLink".
 */
export interface EvidenceLink {
  evidenceId: string;
  source: string | null;
  sourceVersion: string | null;
  availableTime: string | null;
  excerpt: string | null;
  locator: string | null;
  access: "DIRECT_URL" | "REFERENCE_ONLY";
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
 * This interface was referenced by `KolClaimExtractionCandidate`'s JSON-Schema
 * via the `definition` "ClaimAction".
 */
export type ClaimAction = "BUY" | "SELL" | "HOLDING" | "WATCH";
/**
 * This interface was referenced by `KolClaimExtractionCandidate`'s JSON-Schema
 * via the `definition` "ClaimPolarity".
 */
export type ClaimPolarity = "AFFIRMED" | "NEGATED";
/**
 * This interface was referenced by `KolClaimExtractionCandidate`'s JSON-Schema
 * via the `definition` "ClaimConditionality".
 */
export type ClaimConditionality = "UNCONDITIONAL" | "CONDITIONAL";
/**
 * This interface was referenced by `KolClaimExtractionCandidate`'s JSON-Schema
 * via the `definition` "ClaimStatementKind".
 */
export type ClaimStatementKind = "DIRECT" | "QUOTE" | "PARAPHRASE" | "AMBIGUOUS";
/**
 * This interface was referenced by `KolClaimExtractionCandidate`'s JSON-Schema
 * via the `definition` "ClaimAttribution".
 */
export type ClaimAttribution = "SELF" | "QUOTED" | "REPORTED" | "UNKNOWN";
/**
 * This interface was referenced by `KolClaimExtractionCandidate`'s JSON-Schema
 * via the `definition` "EventTimeStatus".
 */
export type EventTimeStatus = "EXACT" | "DATE_ONLY" | "UNKNOWN";
/**
 * This interface was referenced by `KolClaimExtractionCandidate`'s JSON-Schema
 * via the `definition` "EvidenceGrade".
 */
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
/**
 * This interface was referenced by `KolClaimExtractionCandidate`'s JSON-Schema
 * via the `definition` "ContentExactAnchor".
 */
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
/**
 * This interface was referenced by `KolClaimExtractionCandidate`'s JSON-Schema
 * via the `definition` "MediaExactAnchor".
 */
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
 * This interface was referenced by `KolClaimExtractionCandidate`'s JSON-Schema
 * via the `definition` "AnchorBase".
 */
export interface AnchorBase {
  anchorType?: "CONTENT" | "MEDIA";
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
  evidenceId?: string;
  evidenceRevisionId?: string;
  evidenceAvailableTime?: string;
  mediaId?: string;
  mediaVersion?: string;
  mediaManifestRevisionId?: string;
  /**
   * @minItems 1
   * @maxItems 1000
   */
  segmentIndexes?: [number, ...number[]];
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

/**
 * This interface was referenced by `KolClaim`'s JSON-Schema
 * via the `definition` "KolClaimSchemaVersion".
 */
export type KolClaimSchemaVersion = "kol-claim-v1";
/**
 * This interface was referenced by `KolClaim`'s JSON-Schema
 * via the `definition` "KolClaimStatementKind".
 */
export type KolClaimStatementKind = "DIRECT" | "QUOTE" | "PARAPHRASE" | "AMBIGUOUS";
/**
 * This interface was referenced by `KolClaim`'s JSON-Schema
 * via the `definition` "KolClaimDirection".
 */
export type KolClaimDirection = "BULLISH" | "BEARISH" | "NEUTRAL";
/**
 * This interface was referenced by `KolClaim`'s JSON-Schema
 * via the `definition` "KolClaimAttribution".
 */
export type KolClaimAttribution = "SELF" | "QUOTED" | "REPORTED" | "UNKNOWN";
/**
 * This interface was referenced by `KolClaim`'s JSON-Schema
 * via the `definition` "KolClaimUncertainty".
 */
export type KolClaimUncertainty = "NONE" | "AMBIGUOUS" | "CONDITIONAL" | "UNVERIFIED";
/**
 * This interface was referenced by `KolClaim`'s JSON-Schema
 * via the `definition` "KolClaimReviewStatus".
 */
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
/**
 * This interface was referenced by `KolClaim`'s JSON-Schema
 * via the `definition` "KolClaimEvidenceReference".
 */
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

/**
 * This interface was referenced by `KolContent`'s JSON-Schema
 * via the `definition` "KolContentSchemaVersion".
 */
export type KolContentSchemaVersion = "kol-content-v1";
/**
 * This interface was referenced by `KolContent`'s JSON-Schema
 * via the `definition` "KolContentType".
 */
export type KolContentType = "POST" | "ARTICLE" | "VIDEO" | "AUDIO" | "COMMENT" | "OTHER";
/**
 * This interface was referenced by `KolContent`'s JSON-Schema
 * via the `definition` "KolContentFingerprintAlgorithmVersion".
 */
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

/**
 * This interface was referenced by `KolEvidence`'s JSON-Schema
 * via the `definition` "KolEvidenceSchemaVersion".
 */
export type KolEvidenceSchemaVersion = "kol-evidence-v1";
/**
 * This interface was referenced by `KolEvidence`'s JSON-Schema
 * via the `definition` "KolEvidenceLocatorType".
 */
export type KolEvidenceLocatorType = "URL" | "TEXT_RANGE" | "TIME_RANGE" | "PAGE";
/**
 * This interface was referenced by `KolEvidence`'s JSON-Schema
 * via the `definition` "KolEvidenceGrade".
 */
export type KolEvidenceGrade =
  "PRIMARY_SOURCE" | "SECONDARY_SOURCE" | "TERTIARY_SOURCE" | "UNCLASSIFIED";
/**
 * This interface was referenced by `KolEvidence`'s JSON-Schema
 * via the `definition` "KolEvidenceGradeVersion".
 */
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

/**
 * This interface was referenced by `KolMediaTextEvidence`'s JSON-Schema
 * via the `definition` "MediaTextEvidenceSchemaVersion".
 */
export type MediaTextEvidenceSchemaVersion = "kol-media-text-evidence-v1";
/**
 * This interface was referenced by `KolMediaTextEvidence`'s JSON-Schema
 * via the `definition` "MediaKind".
 */
export type MediaKind = "AUDIO" | "VIDEO" | "IMAGE";
/**
 * This interface was referenced by `KolMediaTextEvidence`'s JSON-Schema
 * via the `definition` "MediaProcessorKind".
 */
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
/**
 * This interface was referenced by `KolMediaTextEvidence`'s JSON-Schema
 * via the `definition` "MediaManifest".
 */
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
/**
 * This interface was referenced by `KolMediaTextEvidence`'s JSON-Schema
 * via the `definition` "MediaTextSegment".
 */
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
/**
 * This interface was referenced by `KolMediaTextEvidence`'s JSON-Schema
 * via the `definition` "MediaBoundingBox".
 */
export interface MediaBoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}
/**
 * This interface was referenced by `KolMediaTextEvidence`'s JSON-Schema
 * via the `definition` "MediaEvidenceProvenance".
 */
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

/**
 * This interface was referenced by `KolMention`'s JSON-Schema
 * via the `definition` "KolMentionSchemaVersion".
 */
export type KolMentionSchemaVersion = "kol-mention-v1";
/**
 * This interface was referenced by `KolMention`'s JSON-Schema
 * via the `definition` "KolMentionType".
 */
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

/**
 * This interface was referenced by `KolPositionClaim`'s JSON-Schema
 * via the `definition` "KolPositionClaimSchemaVersion".
 */
export type KolPositionClaimSchemaVersion = "kol-position-claim-v1";
/**
 * This interface was referenced by `KolPositionClaim`'s JSON-Schema
 * via the `definition` "KolPositionDirection".
 */
export type KolPositionDirection = "LONG" | "SHORT" | "FLAT";
/**
 * This interface was referenced by `KolPositionClaim`'s JSON-Schema
 * via the `definition` "KolPositionTimeHorizon".
 */
export type KolPositionTimeHorizon = "INTRADAY" | "SWING" | "LONG_TERM" | "UNSPECIFIED";
/**
 * This interface was referenced by `KolPositionClaim`'s JSON-Schema
 * via the `definition` "KolExecutionSemantics".
 */
export type KolExecutionSemantics = "NON_EXECUTABLE_POSITION_CLAIM";
/**
 * This interface was referenced by `KolPositionClaim`'s JSON-Schema
 * via the `definition` "KolPositionReviewStatus".
 */
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
 * This interface was referenced by `MarketDataSettingsResponse`'s JSON-Schema
 * via the `definition` "MarketDataProvider".
 */
export type MarketDataProvider = "akshare" | "tushare";
/**
 * This interface was referenced by `MarketDataSettingsResponse`'s JSON-Schema
 * via the `definition` "MarketDataTokenAction".
 */
export type MarketDataTokenAction = "KEEP" | "REPLACE" | "CLEAR";

/**
 * Safe instance-level market-data provider settings; secrets are never returned to browser clients.
 */
export interface MarketDataSettingsResponse {
  schemaVersion: "market-data-settings-v1";
  provider: MarketDataProvider;
  revision: number;
  tokenConfigured: boolean;
  updatedAt: string | null;
}
/**
 * Compare-and-set update for instance-level market-data provider settings.
 *
 * This interface was referenced by `MarketDataSettingsResponse`'s JSON-Schema
 * via the `definition` "MarketDataSettingsUpdateRequest".
 */
export interface MarketDataSettingsUpdateRequest {
  schemaVersion: "market-data-settings-update-v1";
  expectedRevision: number;
  provider: MarketDataProvider;
  tokenAction: MarketDataTokenAction;
  token?: string;
}
/**
 * Effective settings for the dedicated data worker service; never served to browser routes.
 *
 * This interface was referenced by `MarketDataSettingsResponse`'s JSON-Schema
 * via the `definition` "MarketDataWorkerSettingsResponse".
 */
export interface MarketDataWorkerSettingsResponse {
  schemaVersion: "market-data-worker-settings-v1";
  provider: MarketDataProvider;
  revision: number;
  token: string | null;
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
 * This interface was referenced by `PaperAccountSnapshot`'s JSON-Schema
 * via the `definition` "NonNegativeDecimal".
 */
export type NonNegativeDecimal = string;
/**
 * This interface was referenced by `PaperAccountSnapshot`'s JSON-Schema
 * via the `definition` "PositiveDecimal".
 */
export type PositiveDecimal = string;

/**
 * Point-in-time projection of a simulation-only account ledger
 */
export interface PaperAccountSnapshot {
  schemaVersion: "paper-account-snapshot-v1";
  accountId: string;
  name: string;
  status: "ACTIVE" | "SUSPENDED" | "CLOSED";
  baseCurrency: "CNY";
  initialCapital: NonNegativeDecimal;
  cash: NonNegativeDecimal;
  positions: PaperPosition[];
  latestValuation: PaperValuation | null;
  requestedAsOf: string;
  dataCutoffTime: string;
  eventCount: number;
  eventChainDigest: string;
  stateDigest: string;
  executionCapability: "PAPER_ONLY";
  dataMeaning: "SIMULATION_ONLY_NO_BROKER_PATH";
}
/**
 * This interface was referenced by `PaperAccountSnapshot`'s JSON-Schema
 * via the `definition` "PaperPosition".
 */
export interface PaperPosition {
  instrumentId: string;
  quantity: number;
  availableQuantity: number;
  costAmount: NonNegativeDecimal;
  averageCost: NonNegativeDecimal;
}
/**
 * This interface was referenced by `PaperAccountSnapshot`'s JSON-Schema
 * via the `definition` "PaperValuation".
 */
export interface PaperValuation {
  valuationId: string;
  valuationTime: string;
  availableTime: string;
  cash: NonNegativeDecimal;
  positionMarketValue: NonNegativeDecimal;
  nav: NonNegativeDecimal;
  marks: PaperValuationMark[];
}
/**
 * This interface was referenced by `PaperAccountSnapshot`'s JSON-Schema
 * via the `definition` "PaperValuationMark".
 */
export interface PaperValuationMark {
  instrumentId: string;
  price: PositiveDecimal;
  quantity: number;
  marketValue: NonNegativeDecimal;
  markTime: string;
  availableTime: string;
  source: "EXECUTABLE_QUOTE" | "MARKET_CLOSE" | "STALE_FALLBACK";
  sourceVersion: string;
  evidenceId: string;
}

/**
 * This interface was referenced by `PaperAllocationDecision`'s JSON-Schema
 * via the `definition` "WeightValue".
 */
export type WeightValue = string;
/**
 * This interface was referenced by `PaperAllocationDecision`'s JSON-Schema
 * via the `definition` "DecimalValue".
 */
export type DecimalValue = string;

/**
 * Explainable signal-to-target allocation for simulation-only execution
 */
export interface PaperAllocationDecision {
  schemaVersion: "paper-allocation-decision-v1";
  decisionId: string;
  accountId: string;
  decisionTime: string;
  accountStateDigest: string;
  policyId: string;
  policyVersion: string;
  policyDigest: string;
  targets: PaperTargetPosition[];
  intents: PaperOrderIntent[];
  rejections: PaperAllocationRejection[];
  decisionDigest: string;
  executionCapability: "PAPER_ONLY";
  dataMeaning: "INTENT_ONLY_NO_BROKER_PATH";
}
/**
 * This interface was referenced by `PaperAllocationDecision`'s JSON-Schema
 * via the `definition` "PaperTargetPosition".
 */
export interface PaperTargetPosition {
  instrumentId: string;
  /**
   * @minItems 1
   */
  sourceSignalIds: [string, ...string[]];
  currentQuantity: number;
  targetQuantity: number;
  targetWeight: WeightValue;
  referencePrice: DecimalValue;
  roundingLotSize: number;
  explanation: string;
}
/**
 * This interface was referenced by `PaperAllocationDecision`'s JSON-Schema
 * via the `definition` "PaperOrderIntent".
 */
export interface PaperOrderIntent {
  schemaVersion: "paper-order-intent-v1";
  intentId: string;
  accountId: string;
  /**
   * @minItems 1
   */
  sourceSignalIds: [string, ...string[]];
  instrumentId: string;
  decisionTime: string;
  side: "BUY" | "SELL";
  quantity: number;
  referencePrice: DecimalValue;
  targetQuantity: number;
  targetWeight: WeightValue;
  policyId: string;
  policyVersion: string;
  policyDigest: string;
  explanation: string;
  brokerExecutable: false;
  executionCapability: "PAPER_ONLY";
}
/**
 * This interface was referenced by `PaperAllocationDecision`'s JSON-Schema
 * via the `definition` "PaperAllocationRejection".
 */
export interface PaperAllocationRejection {
  instrumentId: string;
  /**
   * @minItems 1
   */
  sourceSignalIds: [string, ...string[]];
  reason:
    | "ACCOUNT_NOT_ACTIVE"
    | "CONFLICTING_SIGNALS"
    | "LOW_CONFIDENCE"
    | "SHORT_NOT_SUPPORTED"
    | "MISSING_MARKET_DATA"
    | "FUTURE_DATA"
    | "MISSING_VALUATION"
    | "BOARD_LOT_ROUNDED_TO_ZERO"
    | "INSUFFICIENT_CASH"
    | "NO_ACTION";
  explanation: string;
}

/**
 * This interface was referenced by `PaperExecutionWorkspace`'s JSON-Schema
 * via the `definition` "PaperExecutionDecimalValue".
 */
export type PaperExecutionDecimalValue = string;

/**
 * Replayed simulation-only order lifecycle with audit and alerts
 */
export interface PaperExecutionWorkspace {
  schemaVersion: "paper-execution-workspace-v1";
  accountId: string;
  orders: PaperOrder[];
  audits: PaperOrderAudit[];
  alerts: PaperOrderAlert[];
  eventCount: number;
  eventChainDigest: string;
  stateDigest: string;
  executionCapability: "PAPER_ONLY";
  dataMeaning: "SIMULATED_EXECUTION_NO_BROKER_PATH";
}
/**
 * This interface was referenced by `PaperExecutionWorkspace`'s JSON-Schema
 * via the `definition` "PaperOrder".
 */
export interface PaperOrder {
  schemaVersion: "paper-order-v1";
  orderId: string;
  clientOrderId: string;
  intentId: string;
  instrumentId: string;
  side: "BUY" | "SELL";
  quantity: number;
  filledQuantity: number;
  remainingQuantity: number;
  averageFillPrice: PaperExecutionDecimalValue | null;
  totalFees: PaperExecutionDecimalValue;
  status:
    | "CREATED"
    | "CHECKED"
    | "SUBMITTED"
    | "PARTIALLY_FILLED"
    | "CANCEL_PENDING"
    | "FILLED"
    | "CANCELLED"
    | "REJECTED";
  riskDecisionId: string | null;
  fills: PaperFill[];
  createdAt: string;
  submittedAt: string | null;
  updatedAt: string;
  executionCapability: "PAPER_ONLY";
}
/**
 * This interface was referenced by `PaperExecutionWorkspace`'s JSON-Schema
 * via the `definition` "PaperFill".
 */
export interface PaperFill {
  fillId: string;
  quantity: number;
  price: PaperExecutionDecimalValue;
  fee: PaperExecutionDecimalValue;
  eventTime: string;
  availableTime: string;
  liquidityEvidenceId: string;
}
/**
 * This interface was referenced by `PaperExecutionWorkspace`'s JSON-Schema
 * via the `definition` "PaperOrderAudit".
 */
export interface PaperOrderAudit {
  eventId: string;
  orderId: string;
  eventType: string;
  outcome: "APPLIED" | "DUPLICATE" | "REJECTED";
  detail: string;
  availableTime: string;
}
/**
 * This interface was referenced by `PaperExecutionWorkspace`'s JSON-Schema
 * via the `definition` "PaperOrderAlert".
 */
export interface PaperOrderAlert {
  alertId: string;
  eventId: string;
  orderId: string;
  code:
    | "ILLEGAL_ORDER_TRANSITION"
    | "IDEMPOTENCY_CONFLICT"
    | "UNKNOWN_ORDER"
    | "FILL_CONFLICT"
    | "OVERFILL_REJECTED";
  detail: string;
  availableTime: string;
}

/**
 * Point-in-time reconciliation between execution-derived and account books
 */
export interface PaperReconciliationResult {
  schemaVersion: "paper-reconciliation-result-v1";
  reconciliationId: string;
  accountId: string;
  asOf: string;
  status: "MATCHED" | "DRIFTED";
  expectedBookDigest: string;
  observedBookDigest: string;
  diffs: PaperBookDiff[];
  duplicateFillCount: number;
  executionCapability: "PAPER_ONLY";
  dataMeaning: "SIMULATION_BOOK_RECONCILIATION";
}
/**
 * This interface was referenced by `PaperReconciliationResult`'s JSON-Schema
 * via the `definition` "PaperBookDiff".
 */
export interface PaperBookDiff {
  kind: "CASH" | "POSITION_QUANTITY" | "POSITION_COST";
  instrumentId: string | null;
  expected: string;
  observed: string;
  difference: string;
}

/**
 * Fail-closed pre-trade risk decision bound to immutable account and execution state
 */
export interface PaperRiskDecision {
  schemaVersion: "paper-risk-decision-v1";
  decisionId: string;
  accountId: string;
  intentId: string;
  decisionTime: string;
  allowed: boolean;
  checks: PaperRiskCheck[];
  accountStateDigest: string;
  executionStateDigest: string;
  policyId: string;
  policyVersion: string;
  policyDigest: string;
  executionCapability: "PAPER_ONLY";
  dataMeaning: "SERVER_SIDE_RISK_NO_BROKER_PATH";
}
/**
 * This interface was referenced by `PaperRiskDecision`'s JSON-Schema
 * via the `definition` "PaperRiskCheck".
 */
export interface PaperRiskCheck {
  code:
    | "ACCOUNT_ACTIVE"
    | "RISK_ENGINE_READY"
    | "EXECUTION_CONNECTED"
    | "RECONCILIATION_HEALTHY"
    | "ORDER_NOTIONAL_LIMIT"
    | "POSITION_WEIGHT_LIMIT"
    | "DAILY_TURNOVER_LIMIT"
    | "OPEN_ORDER_LIMIT"
    | "CASH_AVAILABLE"
    | "PAPER_ONLY_BOUNDARY";
  status: "PASS" | "FAIL";
  actual: string;
  limit: string | null;
  explanation: string;
}

export interface PaperTerminalCreateAccountCommand {
  schemaVersion: "paper-terminal-create-account-v1";
  clientRequestId: string;
  name: string;
  initialCapital: string;
}

export interface PaperTerminalSimulationCommand {
  schemaVersion: "paper-terminal-simulation-v1";
  clientRequestId: string;
  instrumentId: string;
  price: string;
  score: string;
  confidence: string;
  lotSize: number;
}

/**
 * This interface was referenced by `PaperTerminalWorkspace`'s JSON-Schema
 * via the `definition` "Digest".
 */
export type Digest = string;
/**
 * This interface was referenced by `PaperTerminalWorkspace`'s JSON-Schema
 * via the `definition` "Money".
 */
export type Money = string;

export interface PaperTerminalWorkspace {
  schemaVersion: "paper-terminal-workspace-v1";
  status: "EMPTY" | "READY" | "DEGRADED" | "UNAVAILABLE";
  dataMeaning: "SIMULATION_ONLY_NO_BROKER_PATH";
  executionCapability: "PAPER_ONLY";
  persistenceMode: "VOLATILE_IN_MEMORY" | "DURABLE_COMMAND_JOURNAL";
  generatedAt: string;
  /**
   * @minItems 1
   */
  limitations: [string, ...string[]];
  account: PaperTerminalAccount | null;
  latestAllocation: PaperTerminalAllocation | null;
  orders: PaperTerminalOrder[];
  latestRisk: PaperTerminalRisk | null;
  reconciliation: PaperTerminalReconciliation | null;
  audit: PaperTerminalAudit;
}
/**
 * This interface was referenced by `PaperTerminalWorkspace`'s JSON-Schema
 * via the `definition` "PaperTerminalAccount".
 */
export interface PaperTerminalAccount {
  accountId: Digest;
  name: string;
  status: "ACTIVE" | "SUSPENDED" | "CLOSED";
  baseCurrency: "CNY";
  initialCapital: Money;
  cash: Money;
  nav: Money;
  dataCutoffTime: string;
  eventCount: number;
  eventChainDigest: Digest;
  positions: PaperTerminalPosition[];
}
/**
 * This interface was referenced by `PaperTerminalWorkspace`'s JSON-Schema
 * via the `definition` "PaperTerminalPosition".
 */
export interface PaperTerminalPosition {
  instrumentId: string;
  quantity: number;
  availableQuantity: number;
  costAmount: Money;
  marketValue: Money;
}
/**
 * This interface was referenced by `PaperTerminalWorkspace`'s JSON-Schema
 * via the `definition` "PaperTerminalAllocation".
 */
export interface PaperTerminalAllocation {
  decisionId: Digest;
  policyId: string;
  policyVersion: string;
  intentCount: number;
  rejectionCount: number;
  rejections: PaperTerminalAllocationRejection[];
}
/**
 * This interface was referenced by `PaperTerminalWorkspace`'s JSON-Schema
 * via the `definition` "PaperTerminalAllocationRejection".
 */
export interface PaperTerminalAllocationRejection {
  instrumentId: string;
  reason: string;
  explanation: string;
}
/**
 * This interface was referenced by `PaperTerminalWorkspace`'s JSON-Schema
 * via the `definition` "PaperTerminalOrder".
 */
export interface PaperTerminalOrder {
  orderId: Digest;
  instrumentId: string;
  side: "BUY" | "SELL";
  status:
    | "CREATED"
    | "CHECKED"
    | "SUBMITTED"
    | "PARTIALLY_FILLED"
    | "CANCEL_PENDING"
    | "FILLED"
    | "CANCELLED"
    | "REJECTED";
  quantity: number;
  filledQuantity: number;
  averageFillPrice: Money | null;
  totalFees: Money;
  explanation: string;
  updatedAt: string;
}
/**
 * This interface was referenced by `PaperTerminalWorkspace`'s JSON-Schema
 * via the `definition` "PaperTerminalRisk".
 */
export interface PaperTerminalRisk {
  decisionId: Digest;
  allowed: boolean;
  policyId: string;
  policyVersion: string;
  /**
   * @minItems 1
   */
  checks: [PaperTerminalRiskCheck, ...PaperTerminalRiskCheck[]];
}
/**
 * This interface was referenced by `PaperTerminalWorkspace`'s JSON-Schema
 * via the `definition` "PaperTerminalRiskCheck".
 */
export interface PaperTerminalRiskCheck {
  code: string;
  status: "PASS" | "FAIL";
  actual: string;
  limit: string | null;
  explanation: string;
}
/**
 * This interface was referenced by `PaperTerminalWorkspace`'s JSON-Schema
 * via the `definition` "PaperTerminalReconciliation".
 */
export interface PaperTerminalReconciliation {
  reconciliationId: Digest;
  status: "MATCHED" | "DRIFTED";
  asOf: string;
  duplicateFillCount: number;
  diffs: PaperTerminalBookDiff[];
}
/**
 * This interface was referenced by `PaperTerminalWorkspace`'s JSON-Schema
 * via the `definition` "PaperTerminalBookDiff".
 */
export interface PaperTerminalBookDiff {
  kind: string;
  instrumentId: string | null;
  expected: string;
  observed: string;
  difference: string;
}
/**
 * This interface was referenced by `PaperTerminalWorkspace`'s JSON-Schema
 * via the `definition` "PaperTerminalAudit".
 */
export interface PaperTerminalAudit {
  accountEventCount: number;
  executionEventCount: number;
  orderAuditCount: number;
  alertCount: number;
  accountDigest: Digest | null;
  executionDigest: Digest | null;
  lastClientRequestId: string | null;
}

/**
 * This interface was referenced by `RankingTerminalSnapshot`'s JSON-Schema
 * via the `definition` "RankingTerminalDigest".
 */
export type RankingTerminalDigest = string;

export interface RankingTerminalSnapshot {
  snapshotId: RankingTerminalDigest;
  inputFingerprint: RankingTerminalDigest;
  asOf: string;
  generatedAt: string;
  sourceMode: "VERSIONED_RESEARCH_SNAPSHOT";
  spec: RankingTerminalSpec;
  rows: RankingTerminalRow[];
}
/**
 * This interface was referenced by `RankingTerminalSnapshot`'s JSON-Schema
 * via the `definition` "RankingTerminalSpec".
 */
export interface RankingTerminalSpec {
  specId: string;
  version: string;
  algorithmVersion: string;
  fingerprint: RankingTerminalDigest;
  minimumCoverageBps: number;
  /**
   * @minItems 1
   */
  features: [RankingTerminalFeatureSpec, ...RankingTerminalFeatureSpec[]];
}
/**
 * This interface was referenced by `RankingTerminalSnapshot`'s JSON-Schema
 * via the `definition` "RankingTerminalFeatureSpec".
 */
export interface RankingTerminalFeatureSpec {
  key: string;
  label: string;
  weightBps: number;
  direction: "HIGHER_IS_BETTER" | "LOWER_IS_BETTER";
  missingPolicy: "EXCLUDE" | "ZERO" | "RENORMALIZE";
}
/**
 * This interface was referenced by `RankingTerminalSnapshot`'s JSON-Schema
 * via the `definition` "RankingTerminalRow".
 */
export interface RankingTerminalRow {
  instrumentId: string;
  instrumentName: string;
  sector: string;
  status: "INCLUDED" | "EXCLUDED";
  rank: number | null;
  scoreBps: number | null;
  coverageBps: number;
  contributions: RankingTerminalContribution[];
  exclusionReasons: string[];
}
/**
 * This interface was referenced by `RankingTerminalSnapshot`'s JSON-Schema
 * via the `definition` "RankingTerminalContribution".
 */
export interface RankingTerminalContribution {
  featureKey: string;
  label: string;
  direction: "HIGHER_IS_BETTER" | "LOWER_IS_BETTER";
  rawValue: string | null;
  normalizedScoreBps: number | null;
  configuredWeightBps: number;
  effectiveWeightBps: number;
  contributionBps: number;
  missingReason: string | null;
  availableTime: string | null;
  source: string | null;
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
/**
 * This interface was referenced by `SeatKolWorkbenchSnapshot`'s JSON-Schema
 * via the `definition` "seatProfile".
 */
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
/**
 * This interface was referenced by `SeatKolWorkbenchSnapshot`'s JSON-Schema
 * via the `definition` "metric".
 */
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
/**
 * This interface was referenced by `SeatKolWorkbenchSnapshot`'s JSON-Schema
 * via the `definition` "evidence".
 */
export interface SeatKolWorkbenchEvidence {
  evidenceId: string;
  source: string;
  sourceVersion: string;
  availableTime: string;
  excerpt: string;
  locator: string;
}
/**
 * This interface was referenced by `SeatKolWorkbenchSnapshot`'s JSON-Schema
 * via the `definition` "timelineEntry".
 */
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
/**
 * This interface was referenced by `SeatKolWorkbenchSnapshot`'s JSON-Schema
 * via the `definition` "kolProfile".
 */
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
/**
 * This interface was referenced by `SeatKolWorkbenchSnapshot`'s JSON-Schema
 * via the `definition` "claim".
 */
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
/**
 * This interface was referenced by `SeatKolWorkbenchSnapshot`'s JSON-Schema
 * via the `definition` "cooccurrence".
 */
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
/**
 * This interface was referenced by `SeatKolWorkbenchSnapshot`'s JSON-Schema
 * via the `definition` "reviewQueueItem".
 */
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

/**
 * This interface was referenced by `SeatAlias`'s JSON-Schema
 * via the `definition` "SeatAliasSchemaVersion".
 */
export type SeatAliasSchemaVersion = "alias-v1";
/**
 * This interface was referenced by `SeatAlias`'s JSON-Schema
 * via the `definition` "SeatAliasType".
 */
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

/**
 * This interface was referenced by `SeatPerformance`'s JSON-Schema
 * via the `definition` "SeatPerformanceSchemaVersion".
 */
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

/**
 * This interface was referenced by `SeatPreference`'s JSON-Schema
 * via the `definition` "SeatPreferenceSchemaVersion".
 */
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

/**
 * This interface was referenced by `SeatProfile`'s JSON-Schema
 * via the `definition` "SeatProfileSchemaVersion".
 */
export type SeatProfileSchemaVersion = "seat-profile-v1";
/**
 * This interface was referenced by `SeatProfile`'s JSON-Schema
 * via the `definition` "SeatProfileSeatKind".
 */
export type SeatProfileSeatKind = "BROKER_BRANCH" | "INSTITUTION" | "UNKNOWN" | "OTHER";
/**
 * This interface was referenced by `SeatProfile`'s JSON-Schema
 * via the `definition` "SeatProfileLineageRelation".
 */
export type SeatProfileLineageRelation = "MERGE" | "SPLIT";
/**
 * This interface was referenced by `SeatProfile`'s JSON-Schema
 * via the `definition` "SeatProfileSeatIdAlgorithm".
 */
export type SeatProfileSeatIdAlgorithm = "seat-id-v1";

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
/**
 * This interface was referenced by `SeatProfile`'s JSON-Schema
 * via the `definition` "SeatLineage".
 */
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

/**
 * This interface was referenced by `SeatTrade`'s JSON-Schema
 * via the `definition` "SeatTradeSchemaVersion".
 */
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

/**
 * Versioned point-in-time research signal with no execution capability.
 */
export interface Signal {
  schemaVersion: "signal-v1";
  signalId: string;
  strategyId: string;
  strategyVersion: string;
  algorithmVersion: string;
  entityId: string;
  decisionTime: string;
  dataCutoffTime: string;
  direction: "LONG" | "SHORT" | "NEUTRAL";
  score: string;
  confidence: string;
  horizonSessions: number;
  rationale: string;
  inputSnapshotId: string;
  inputSnapshotVersion: string;
  /**
   * @minItems 1
   */
  evidenceIds: [string, ...string[]];
  isExecutable: false;
  executionCapability: "NONE";
}

/**
 * This interface was referenced by `StrategyDescriptor`'s JSON-Schema
 * via the `definition` "Version".
 */
export type Version = string;

/**
 * Research-only strategy metadata, lifecycle and typed parameter contract.
 */
export interface StrategyDescriptor {
  schemaVersion: "strategy-descriptor-v1";
  strategyId: string;
  strategyVersion: Version;
  algorithmVersion: Version;
  sdkVersion: Version;
  lifecycleVersion: Version;
  description: string;
  /**
   * @minItems 1
   */
  requiredFeatures: [string, ...string[]];
  /**
   * @minItems 1
   */
  parameterSpecs: [
    IntegerParameterSpec | DecimalParameterSpec | BooleanParameterSpec | StringParameterSpec,
    ...(IntegerParameterSpec | DecimalParameterSpec | BooleanParameterSpec | StringParameterSpec)[],
  ];
  /**
   * @minItems 3
   * @maxItems 3
   */
  lifecycleHooks: ["initialize", "onDecision", "finalize"];
  signalSchemaVersion: "signal-v1";
  executionCapability: "NONE";
}
/**
 * This interface was referenced by `StrategyDescriptor`'s JSON-Schema
 * via the `definition` "IntegerParameterSpec".
 */
export interface IntegerParameterSpec {
  name: string;
  valueType: "INTEGER";
  required: boolean;
  description: string;
  defaultValue?: number | null;
  minimum?: number | null;
  maximum?: number | null;
}
/**
 * This interface was referenced by `StrategyDescriptor`'s JSON-Schema
 * via the `definition` "DecimalParameterSpec".
 */
export interface DecimalParameterSpec {
  name: string;
  valueType: "DECIMAL";
  required: boolean;
  description: string;
  defaultValue?: string | null;
  minimum?: string | null;
  maximum?: string | null;
}
/**
 * This interface was referenced by `StrategyDescriptor`'s JSON-Schema
 * via the `definition` "BooleanParameterSpec".
 */
export interface BooleanParameterSpec {
  name: string;
  valueType: "BOOLEAN";
  required: boolean;
  description: string;
  defaultValue?: boolean | null;
}
/**
 * This interface was referenced by `StrategyDescriptor`'s JSON-Schema
 * via the `definition` "StringParameterSpec".
 */
export interface StringParameterSpec {
  name: string;
  valueType: "STRING";
  required: boolean;
  description: string;
  defaultValue?: string | null;
}
