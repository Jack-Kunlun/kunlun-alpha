import type { MarketEmotionSnapshot, SectorRotationEvent } from "./emotion-snapshot";

export interface EmotionReplayQuery {
  date: string;
  asOf: string;
  algorithmVersion?: string;
  sectorId?: string;
}

export interface EmotionRepository {
  querySnapshots(query: EmotionReplayQuery): Promise<MarketEmotionSnapshot[]>;
  queryRotationEvents(query: EmotionReplayQuery): Promise<SectorRotationEvent[]>;
  listVersions(): Promise<string[]>;
}
