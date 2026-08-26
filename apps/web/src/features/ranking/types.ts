export type RankingDirection = "HIGHER_IS_BETTER" | "LOWER_IS_BETTER";
export type MissingFeaturePolicy = "EXCLUDE" | "ZERO" | "RENORMALIZE";
export type RankingRowStatus = "INCLUDED" | "EXCLUDED";

export interface RankingFeatureSpec {
  key: string;
  label: string;
  weightBps: number;
  direction: RankingDirection;
  missingPolicy: MissingFeaturePolicy;
}

export interface RankingSpec {
  specId: string;
  version: string;
  algorithmVersion: string;
  fingerprint: string;
  minimumCoverageBps: number;
  features: readonly RankingFeatureSpec[];
}

export interface RankingContribution {
  featureKey: string;
  label: string;
  direction: RankingDirection;
  rawValue: string | null;
  normalizedScoreBps: number | null;
  configuredWeightBps: number;
  effectiveWeightBps: number;
  contributionBps: number;
  missingReason: string | null;
  availableTime: string | null;
  source: string | null;
}

export interface RankingRow {
  instrumentId: string;
  instrumentName: string;
  sector: string;
  status: RankingRowStatus;
  rank: number | null;
  scoreBps: number | null;
  coverageBps: number;
  contributions: readonly RankingContribution[];
  exclusionReasons: readonly string[];
}

export interface RankingSnapshot {
  snapshotId: string;
  inputFingerprint: string;
  asOf: string;
  generatedAt: string;
  sourceMode: "SANITIZED_ACCEPTANCE_FIXTURE";
  spec: RankingSpec;
  rows: readonly RankingRow[];
}

export interface RankingFilters {
  query: string;
  sector: string | null;
  minimumScoreBps: number | null;
  includeExcluded: boolean;
}

export type RankingTerminalResult =
  | { state: "loading" }
  | { state: "forbidden"; message: string }
  | { state: "error"; message: string }
  | { state: "success"; snapshot: RankingSnapshot };
