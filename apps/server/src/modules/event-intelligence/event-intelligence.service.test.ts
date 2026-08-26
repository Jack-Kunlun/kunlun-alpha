import { ForbiddenException } from "@nestjs/common";
import type { HotTopicSnapshot, MarketEvent } from "@kunlun/shared-types";
import { describe, expect, it } from "vitest";
import { InMemoryEventIntelligenceRepository } from "./in-memory-event-intelligence.repository";
import { EventIntelligenceService } from "./event-intelligence.service";

const event = {
  schemaVersion: "market-event-v1",
  eventId: "a".repeat(64),
  eventType: "CORPORATE",
  headline: "重大事项",
  summary: "重大事项摘要",
  occurTime: "2026-08-24T01:00:00.000Z",
  publishTime: "2026-08-24T01:00:00.000Z",
  availableTime: "2026-08-24T02:00:00.000Z",
  instrumentIds: ["600519.SH"],
  sectorIds: ["sector-food"],
  evidence: [
    {
      evidenceId: "evidence-1",
      contentRecordId: "content-1",
      contentVersionId: "c".repeat(64),
      sourceId: "source-1",
      sourceVersion: "source-v1",
      availableTime: "2026-08-24T02:00:00.000Z",
      startOffset: 0,
      endOffset: 4,
      excerpt: "重大事项",
    },
  ],
  modelProvenance: {
    producerType: "MODEL",
    provider: "provider-1",
    modelId: "model-1",
    modelVersion: "model-v1",
    promptVersion: "prompt-v1",
    outputSchemaVersion: "market-event-v1",
    configurationFingerprint: "d".repeat(64),
    extractionRunId: "run-1",
    processingTime: "2026-08-24T02:00:00.000Z",
  },
  confidenceBps: 8500,
} as unknown as MarketEvent;

const topic = {
  schemaVersion: "hot-topic-snapshot-v1",
  snapshotId: "b".repeat(64),
  topicId: "topic-ai",
  topicName: "人工智能",
  lifecycle: "HOT",
  decisionTime: "2026-08-24T03:00:00.000Z",
  windowStart: "2026-08-23T03:00:00.000Z",
  windowEnd: "2026-08-24T03:00:00.000Z",
  scoreBps: 8000,
  confidenceBps: 7500,
  components: {
    evidenceQualityBps: 8000,
    recencyBps: 7500,
    sourceDiversityBps: 7000,
    breadthBps: 6500,
    momentumBps: 6000,
  },
  eventCount: 1,
  recentEventCount: 1,
  staleEventCount: 0,
  sourceCount: 1,
  instrumentCount: 1,
  sectorCount: 1,
  eventIds: [event.eventId],
  policyFingerprint: "e".repeat(64),
  algorithmVersion: "hot-score-v1",
} as unknown as HotTopicSnapshot;

describe("EventIntelligenceService", () => {
  it("filters events and returns latest topics at asOf", async () => {
    const service = new EventIntelligenceService(
      new InMemoryEventIntelligenceRepository([event], [topic]),
    );
    await expect(service.events({ instrumentId: "600519.SH" })).resolves.toEqual([event]);
    await expect(service.hotTopics({ asOf: "2026-08-24T03:00:00.000Z" })).resolves.toEqual([topic]);
  });

  it("rejects invalid filters and future-invisible topic snapshots", async () => {
    const service = new EventIntelligenceService(
      new InMemoryEventIntelligenceRepository([event], [topic]),
    );
    await expect(service.events({ rawSql: "DROP" })).rejects.toThrow("unknown filter");
    await expect(service.events({ asOf: "2026-08-24T15:00:00" })).rejects.toThrow(
      "asOf must be an ISO-8601 timestamp",
    );
    await expect(service.hotTopics({ asOf: "2026-08-24T15:00:00" })).rejects.toThrow(
      "asOf must be an ISO-8601 timestamp",
    );
    await expect(service.events({ asOf: "2026-02-30T00:00:00Z" })).rejects.toThrow(
      "asOf must be an ISO-8601 timestamp",
    );
    await expect(service.hotTopics({ asOf: "2026-08-24T02:59:59.000Z" })).resolves.toEqual([]);
  });

  it("compares offset hotspot decision times as instants", async () => {
    const visible = {
      ...topic,
      snapshotId: "1".repeat(64),
      decisionTime: "2026-08-24T10:30:00+08:00",
      windowEnd: "2026-08-24T10:30:00+08:00",
    } as HotTopicSnapshot;
    const future = {
      ...topic,
      snapshotId: "2".repeat(64),
      decisionTime: "2026-08-24T02:30:00-02:00",
      windowEnd: "2026-08-24T02:30:00-02:00",
    } as HotTopicSnapshot;
    const service = new EventIntelligenceService(
      new InMemoryEventIntelligenceRepository([], [visible, future]),
    );
    await expect(service.hotTopics({ asOf: "2026-08-24T03:00:00Z" })).resolves.toEqual([visible]);
  });

  it("returns complete exact-ID evidence across days and cuts unavailable records", async () => {
    const visibleEvents = Array.from({ length: 101 }, (_, index) => ({
      ...event,
      eventId: index.toString(16).padStart(64, "0"),
      availableTime: "2026-08-23T16:30:00.000Z",
    })) as MarketEvent[];
    const unavailable = {
      ...event,
      eventId: "f".repeat(64),
      availableTime: "2026-08-24T04:00:00.000Z",
    } as MarketEvent;
    const service = new EventIntelligenceService(
      new InMemoryEventIntelligenceRepository([...visibleEvents, unavailable]),
    );
    const eventIds = [...visibleEvents.map((item) => item.eventId), unavailable.eventId];
    const result = await service.events({
      eventIds: eventIds.join(","),
      asOf: "2026-08-24T03:00:00.000Z",
      limit: String(eventIds.length),
    });
    expect(result).toHaveLength(101);
    expect(result.some((item) => item.eventId === unavailable.eventId)).toBe(false);
    await expect(
      service.events({ dateFrom: "2026-08-24", dateTo: "2026-08-24", limit: "200" }),
    ).resolves.toHaveLength(102);
  });

  it("supports a controlled forbidden state", async () => {
    const service = new EventIntelligenceService(new InMemoryEventIntelligenceRepository(), {
      canRead: async () => false,
    });
    await expect(service.events({})).rejects.toThrow(ForbiddenException);
  });
});
