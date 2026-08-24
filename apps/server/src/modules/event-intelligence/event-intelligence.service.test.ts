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
  evidence: [{}],
  modelProvenance: {},
  confidenceBps: 8500,
} as unknown as MarketEvent;

const topic = {
  schemaVersion: "hot-topic-snapshot-v1",
  snapshotId: "b".repeat(64),
  topicId: "topic-ai",
  topicName: "人工智能",
  lifecycle: "HOT",
  decisionTime: "2026-08-24T03:00:00.000Z",
  scoreBps: 8000,
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
    await expect(service.hotTopics({ asOf: "2026-08-24T02:59:59.000Z" })).resolves.toEqual([]);
  });

  it("supports a controlled forbidden state", async () => {
    const service = new EventIntelligenceService(new InMemoryEventIntelligenceRepository(), {
      canRead: async () => false,
    });
    await expect(service.events({})).rejects.toThrow(ForbiddenException);
  });
});
