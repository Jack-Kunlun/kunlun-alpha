import type {
  LimitPoolListingBoard,
  LimitPoolSide,
  LimitPoolState,
  LimitPoolTerminalCompleteness,
} from "@kunlun/shared-types";

export interface StoredLimitPoolEntry {
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
  priceCny: string;
  previousCloseCny: string;
  firstSealTime: string | null;
  lastSealTime: string | null;
  eventTime: string;
  availableTime: string;
  revision: number;
  sourceVersion: string;
  evidenceId: string;
}

export interface StoredLimitPoolLadderLevel {
  streakDays: number;
  count: number;
  previousDayEligibleCount: number;
  promotedCount: number;
}

export interface StoredLimitPoolPayload {
  tradingDate: string;
  previousTradingDate: string | null;
  completeness: Exclude<LimitPoolTerminalCompleteness, "EMPTY">;
  missingReasons: string[];
  limitUpCount: number;
  limitDownCount: number;
  sealedCount: number;
  totalOpenCount: number;
  ladder: StoredLimitPoolLadderLevel[];
  entries: StoredLimitPoolEntry[];
}

export interface StoredLimitPoolSnapshot {
  tradingDate: string;
  eventTime: string;
  availableTime: string;
  revision: number;
  algorithmVersion: string;
  ladderAlgorithmVersion: string;
  limitRuleVersion: string;
  materializerVersion: string;
  sourceVersions: string[];
  evidenceIds: string[];
  payload: StoredLimitPoolPayload;
}

export interface LimitPoolRepositoryQuery {
  asOf: string;
  algorithmVersion?: string;
  ladderAlgorithmVersion?: string;
  limitRuleVersion?: string;
  materializerVersion?: string;
}

export interface LimitPoolRepository {
  findSnapshot(query: LimitPoolRepositoryQuery): Promise<StoredLimitPoolSnapshot | null>;
}
