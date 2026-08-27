import type {
  RankingTerminalContribution,
  RankingTerminalFeatureSpec,
  RankingTerminalRow,
  RankingTerminalSnapshot,
  RankingTerminalSpec,
} from "@kunlun/shared-types";

export type RankingSnapshot = RankingTerminalSnapshot;
export type RankingSpec = RankingTerminalSpec;
export type RankingFeatureSpec = RankingTerminalFeatureSpec;
export type RankingContribution = RankingTerminalContribution;
export type RankingRow = RankingTerminalRow;
export type RankingDirection = RankingFeatureSpec["direction"];
export type MissingFeaturePolicy = RankingFeatureSpec["missingPolicy"];
export type RankingRowStatus = RankingRow["status"];

export interface RankingFilters {
  query: string;
  sector: string | null;
  minimumScoreBps: number | null;
  includeExcluded: boolean;
}

export type RankingTerminalResult =
  | { state: "loading" }
  | { state: "empty"; message: string }
  | { state: "forbidden"; message: string }
  | { state: "error"; message: string }
  | { state: "success"; snapshot: RankingSnapshot };
