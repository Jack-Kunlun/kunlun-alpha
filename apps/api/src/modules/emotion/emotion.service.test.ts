import { describe, expect, it } from "vitest";
import { EmotionService } from "./emotion.service";
import type { EmotionSnapshot } from "./emotion-snapshot";

const snapshots: EmotionSnapshot[] = [
  {
    date: "2026-08-13",
    timestamp: "2026-08-13T01:31:00.000Z",
    score: 0.5,
    version: "emotion_score_v1",
    ladder: [{ board: 3, count: 2 }],
  },
  {
    date: "2026-08-13",
    timestamp: "2026-08-13T01:30:00.000Z",
    score: 0.4,
    version: "emotion_score_v1",
    ladder: [{ board: 2, count: 3 }],
  },
  {
    date: "2026-08-14",
    timestamp: "2026-08-14T01:30:00.000Z",
    score: 0.7,
    version: "emotion_score_v1",
    ladder: [],
  },
];

describe("EmotionService", () => {
  it("replays a trading day ordered by timestamp", () => {
    const service = new EmotionService(snapshots);
    const result = service.query("2026-08-13");
    expect(result.map((s) => s.timestamp)).toEqual([
      "2026-08-13T01:30:00.000Z",
      "2026-08-13T01:31:00.000Z",
    ]);
  });

  it("returns empty for an unknown date", () => {
    const service = new EmotionService(snapshots);
    expect(service.query("2026-08-15")).toEqual([]);
  });

  it("lists distinct algorithm versions", () => {
    const service = new EmotionService(snapshots);
    expect(service.versions()).toEqual(["emotion_score_v1"]);
  });

  it("carries the algorithm version on each snapshot", () => {
    const service = new EmotionService(snapshots);
    for (const snapshot of service.query("2026-08-13")) {
      expect(snapshot.version).toBe("emotion_score_v1");
    }
  });
});
