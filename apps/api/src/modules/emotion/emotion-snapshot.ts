/**
 * Emotion snapshot for replay.
 *
 * A snapshot carries its algorithm version so historical replay always shows
 * the version that produced the score. Real-time and historical endpoints
 * share the same shape, so their semantics stay identical.
 */

export interface LadderEntry {
  board: number;
  count: number;
}

export interface EmotionSnapshot {
  date: string;
  timestamp: string;
  score: number;
  version: string;
  ladder: LadderEntry[];
}
