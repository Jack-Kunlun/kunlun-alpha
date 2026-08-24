import type { MarketEmotionSnapshot, SectorRotationEvent } from "./emotion-snapshot";
import type { EmotionReplayQuery, EmotionRepository } from "./emotion-repository";

export class InMemoryEmotionRepository implements EmotionRepository {
  constructor(
    private readonly snapshots: MarketEmotionSnapshot[] = [],
    private readonly events: SectorRotationEvent[] = [],
  ) {}

  async querySnapshots(query: EmotionReplayQuery): Promise<MarketEmotionSnapshot[]> {
    return [...this.snapshots]
      .filter(
        (snapshot) =>
          snapshot.date === query.date &&
          (query.algorithmVersion === undefined ||
            snapshot.algorithmVersion === query.algorithmVersion),
      )
      .sort(
        (left, right) =>
          left.timestamp.localeCompare(right.timestamp) ||
          left.algorithmVersion.localeCompare(right.algorithmVersion),
      );
  }

  async queryRotationEvents(query: EmotionReplayQuery): Promise<SectorRotationEvent[]> {
    return [...this.events]
      .filter(
        (event) =>
          event.date === query.date &&
          (query.algorithmVersion === undefined ||
            event.algorithmVersion === query.algorithmVersion) &&
          (query.sectorId === undefined ||
            event.fromSector === query.sectorId ||
            event.toSector === query.sectorId),
      )
      .sort(
        (left, right) =>
          left.timestamp.localeCompare(right.timestamp) ||
          left.eventId.localeCompare(right.eventId),
      );
  }

  async listVersions(): Promise<string[]> {
    return [
      ...new Set([
        ...this.snapshots.map((snapshot) => snapshot.algorithmVersion),
        ...this.events.map((event) => event.algorithmVersion),
      ]),
    ].sort();
  }
}
