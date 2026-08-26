import { describe, expect, it } from "vitest";
import type { QueryResult } from "@/lib/use-api-query";
import type {
  HotTopicSnapshot,
  MarketEmotionSnapshot,
  MarketEvent,
  SectorRotationEvent,
} from "./types";
import {
  combineRotationTerminalResults,
  marketEventEvidenceQueries,
  rotationTerminalQueries,
} from "./use-rotation-terminal";

function result<T>(data: T[]): QueryResult<T> {
  return { status: data.length === 0 ? "empty" : "success", data, error: null };
}

const snapshot = {
  date: "2026-08-24",
  timestamp: "2026-08-24T02:00:00.000Z",
  score: 0.5,
  algorithmVersion: "emotion_score_v1",
  ladder: [],
  freshnessSeconds: 10,
  sampleSize: 100,
  confidence: 0.9,
  sourceVersions: ["limit-v2"],
  evidenceIds: ["snapshot-1"],
} as MarketEmotionSnapshot;

const rotation = {
  eventId: "a".repeat(64),
  date: "2026-08-24",
  eventType: "CROSSOVER",
  fromSector: "黄金",
  toSector: "白银",
  timestamp: "2026-08-24T02:05:00.000Z",
  confidence: 0.8,
  evidenceStart: "2026-08-24T02:00:00.000Z",
  evidenceEnd: "2026-08-24T02:05:00.000Z",
  sampleSize: 6,
  algorithmVersion: "rotation_event_v2",
  sourceVersions: ["snapshot-v2"],
  evidenceIds: ["rotation-evidence-1"],
} as SectorRotationEvent;

const topic = {
  snapshotId: "b".repeat(64),
  topicId: "topic-ai",
  topicName: "人工智能",
  lifecycle: "HOT",
  decisionTime: "2026-08-24T02:06:00.000Z",
  eventIds: ["c".repeat(64)],
} as HotTopicSnapshot;

const marketEvent = {
  eventId: "c".repeat(64),
  availableTime: "2026-08-24T02:04:00.000Z",
} as MarketEvent;

describe("rotation terminal query and replay boundary", () => {
  it("builds repository-native replay and point-in-time queries", () => {
    expect(
      rotationTerminalQueries({
        date: "2026-08-24",
        asOf: "2026-08-24T07:00:00.000Z",
        algorithmVersion: "rotation_event_v2",
        sectorId: "sector-gold",
        lifecycle: "HOT",
      }),
    ).toEqual({
      replay: {
        date: "2026-08-24",
        asOf: "2026-08-24T07:00:00.000Z",
        algorithmVersion: "rotation_event_v2",
        sectorId: "sector-gold",
      },
      topics: { asOf: "2026-08-24T07:00:00.000Z", limit: "100", lifecycle: "HOT" },
    });
  });

  it("batches every cross-day hotspot evidence ID without a 100-row truncation", () => {
    const eventIds = Array.from({ length: 101 }, (_, index) =>
      index.toString(16).padStart(64, "0"),
    );
    const queries = marketEventEvidenceQueries(
      [{ ...topic, eventIds }],
      "2026-08-24T07:00:00.000Z",
    );
    expect(queries).toHaveLength(2);
    expect(queries[0]?.eventIds.split(",")).toHaveLength(100);
    expect(queries[0]?.limit).toBe("100");
    expect(queries[1]?.eventIds.split(",")).toHaveLength(1);
    expect(queries[1]?.asOf).toBe("2026-08-24T07:00:00.000Z");
  });

  it("cuts every source at the selected replay point", () => {
    const outcome = combineRotationTerminalResults(
      result([snapshot, { ...snapshot, timestamp: "2026-08-24T03:00:00.000Z" }]),
      result([
        rotation,
        {
          ...rotation,
          eventId: "d".repeat(64),
          timestamp: "2026-08-24T02:10:00.000Z",
          evidenceEnd: "2026-08-24T03:00:00.000Z",
        },
      ]),
      result([
        topic,
        { ...topic, snapshotId: "e".repeat(64), decisionTime: "2026-08-24T03:00:00.000Z" },
      ]),
      result([
        marketEvent,
        { ...marketEvent, eventId: "f".repeat(64), availableTime: "2026-08-24T03:00:00.000Z" },
      ]),
      "2026-08-24T02:30:00.000Z",
    );
    expect(outcome.status).toBe("success");
    expect(outcome.data?.snapshots).toHaveLength(1);
    expect(outcome.data?.rotationEvents).toHaveLength(1);
    expect(outcome.data?.hotTopics).toHaveLength(1);
    expect(outcome.data?.marketEvents).toHaveLength(1);
    expect(outcome.continuity).toContain("已按回放点截断 4 条未来或无效记录");
  });

  it("keeps available data visible while naming a failed source", () => {
    const failed: QueryResult<HotTopicSnapshot> = {
      status: "error",
      data: null,
      error: new Error("offline"),
    };
    const outcome = combineRotationTerminalResults(
      result([snapshot]),
      result([rotation]),
      failed,
      result([marketEvent]),
      "2026-08-24T02:30:00.000Z",
    );
    expect(outcome.status).toBe("partial");
    expect(outcome.data?.rotationEvents).toHaveLength(1);
    expect(outcome.continuity).toContain("热点快照数据源中断");
  });

  it("keeps replay truncation visible when every record is excluded", () => {
    const outcome = combineRotationTerminalResults(
      result([{ ...snapshot, timestamp: "2026-08-24T03:00:00.000Z" }]),
      result([]),
      result([]),
      result([]),
      "2026-08-24T02:30:00.000Z",
    );
    expect(outcome.status).toBe("empty");
    expect(outcome.continuity).toContain("已按回放点截断 1 条未来或无效记录");
  });

  it("marks lifecycle statistics partial when the hotspot limit is reached", () => {
    const topics = Array.from({ length: 100 }, (_, index) => ({
      ...topic,
      snapshotId: index.toString(16).padStart(64, "0"),
      topicId: `topic-${index}`,
      eventIds: [],
    }));
    const outcome = combineRotationTerminalResults(
      result([]),
      result([]),
      result(topics),
      result([]),
      "2026-08-24T02:30:00.000Z",
    );
    expect(outcome.status).toBe("partial");
    expect(outcome.continuity).toContain("热点快照已达到 100 条查询上限，生命周期统计可能不完整");
  });

  it("names a failed source even when no other records remain", () => {
    const failed: QueryResult<MarketEmotionSnapshot> = {
      status: "error",
      data: null,
      error: new Error("offline"),
    };
    const outcome = combineRotationTerminalResults(
      failed,
      result([]),
      result([]),
      result([]),
      "2026-08-24T02:30:00.000Z",
    );
    expect(outcome.status).toBe("error");
    expect(outcome.continuity).toContain("情绪快照数据源中断");
  });
});
