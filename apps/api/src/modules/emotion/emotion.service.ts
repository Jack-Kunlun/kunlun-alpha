import { Inject, Injectable, Optional } from "@nestjs/common";
import type { EmotionSnapshot } from "./emotion-snapshot";

export const EMOTION_SNAPSHOTS = Symbol("EMOTION_SNAPSHOTS");

@Injectable()
export class EmotionService {
  constructor(
    @Optional() @Inject(EMOTION_SNAPSHOTS) private readonly snapshots: EmotionSnapshot[] = [],
  ) {}

  /** Snapshots for a trading day, ordered by timestamp (replay timeline). */
  query(date: string): EmotionSnapshot[] {
    return this.snapshots
      .filter((s) => s.date === date)
      .sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  }

  /** Distinct algorithm versions present in the data. */
  versions(): string[] {
    return [...new Set(this.snapshots.map((s) => s.version))].sort();
  }
}
