import { describe, expect, it } from "vitest";
import type { HotTopicSnapshot, RotationTerminalData } from "./types";
import {
  buildRotationTimeline,
  buildTopicComparison,
  formatShanghaiTime,
} from "./rotation-terminal-model";

function topic(id: string, scoreBps: number, confidenceBps: number): HotTopicSnapshot {
  return {
    snapshotId: id.repeat(64),
    topicId: `topic-${id}`,
    topicName: `热点-${id}`,
    lifecycle: "RISING",
    scoreBps,
    confidenceBps,
    eventCount: 1,
    algorithmVersion: "hot-score-v1",
  } as HotTopicSnapshot;
}

describe("rotation terminal view model", () => {
  it("uses deterministic rows for chart and table", () => {
    expect(buildTopicComparison([topic("a", 7000, 9000), topic("b", 8000, 6000)])).toEqual([
      expect.objectContaining({ topicId: "topic-b", scoreBps: 8000 }),
      expect.objectContaining({ topicId: "topic-a", scoreBps: 7000 }),
    ]);
  });

  it("sorts the unified timeline newest-first", () => {
    const data = {
      asOf: "2026-08-24T03:00:00.000Z",
      snapshots: [],
      hotTopics: [
        {
          ...topic("a", 7000, 9000),
          decisionTime: "2026-08-24T02:10:00.000Z",
          policyFingerprint: "f".repeat(64),
          eventIds: [],
          windowStart: "2026-08-24T01:10:00.000Z",
          windowEnd: "2026-08-24T02:10:00.000Z",
        },
      ],
      rotationEvents: [],
      marketEvents: [],
    } as RotationTerminalData;
    expect(buildRotationTimeline(data)[0]?.title).toBe("热点-a");
  });

  it("links a structured event timeline item to its own evidence payload", () => {
    const eventId = "c".repeat(64);
    const data = {
      asOf: "2026-08-24T03:00:00.000Z",
      snapshots: [],
      hotTopics: [],
      rotationEvents: [],
      marketEvents: [
        {
          eventId,
          availableTime: "2026-08-24T02:10:00.000Z",
          occurTime: "2026-08-24T02:00:00.000Z",
          headline: "产业事件",
          eventType: "INDUSTRY",
          confidenceBps: 8000,
          evidence: [{ evidenceId: "evidence-1", sourceVersion: "source-v1" }],
          modelProvenance: { modelVersion: "model-v1", promptVersion: "prompt-v1" },
        },
      ],
    } as unknown as RotationTerminalData;
    expect(buildRotationTimeline(data)[0]?.relatedEventIds).toEqual([eventId]);
  });

  it("formats every visible instant in Asia/Shanghai", () => {
    expect(formatShanghaiTime("2026-08-24T02:10:00.000Z")).toBe("2026-08-24 10:10:00");
  });
});
