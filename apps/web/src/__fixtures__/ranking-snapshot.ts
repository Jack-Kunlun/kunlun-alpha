import acceptanceSnapshot from "./ranking-acceptance-snapshot.json";
import type { RankingSnapshot } from "../features/ranking/types";

export const rankingAcceptanceSnapshot = {
  ...acceptanceSnapshot,
  sourceMode: "VERSIONED_RESEARCH_SNAPSHOT",
} as RankingSnapshot;
