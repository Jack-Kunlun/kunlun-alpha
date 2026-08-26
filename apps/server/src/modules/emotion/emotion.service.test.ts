import { ForbiddenException } from "@nestjs/common";
import { describe, expect, it } from "vitest";
import type { MarketEmotionSnapshot, SectorRotationEvent } from "./emotion-snapshot";
import type { EmotionAuthorizer } from "./emotion-authorizer";
import { InMemoryEmotionRepository } from "./in-memory-emotion.repository";
import { EmotionValidationError } from "./emotion-query";
import { EmotionService } from "./emotion.service";

const snapshots: MarketEmotionSnapshot[] = [
  {
    date: "2026-08-13",
    timestamp: "2026-08-13T01:30:00.000Z",
    score: 0.4,
    algorithmVersion: "emotion_score_v1",
    ladder: [{ board: 2, count: 3 }],
    freshnessSeconds: 12,
    sampleSize: 100,
    confidence: 0.9,
    sourceVersions: ["limit-v2"],
    evidenceIds: ["snapshot-1"],
  },
  {
    date: "2026-08-13",
    timestamp: "2026-08-13T01:30:00.000Z",
    score: 0.45,
    algorithmVersion: "emotion_score_v2",
    ladder: [{ board: 2, count: 3 }],
    freshnessSeconds: 10,
    sampleSize: 101,
    confidence: 0.91,
    sourceVersions: ["limit-v3"],
    evidenceIds: ["snapshot-2"],
  },
];

const events: SectorRotationEvent[] = [
  {
    eventId: "a".repeat(64),
    date: "2026-08-13",
    eventType: "CROSSOVER",
    fromSector: "sector-a",
    toSector: "sector-b",
    timestamp: "2026-08-13T01:35:00.000Z",
    confidence: 0.8,
    evidenceStart: "2026-08-13T01:30:00.000Z",
    evidenceEnd: "2026-08-13T01:35:00.000Z",
    sampleSize: 6,
    algorithmVersion: "rotation_event_v2",
    sourceVersions: ["snapshot-v2"],
    evidenceIds: ["event-1"],
  },
];

const denyAll: EmotionAuthorizer = { canAccess: () => false };

function service(authorizer?: EmotionAuthorizer): EmotionService {
  return new EmotionService(new InMemoryEmotionRepository(snapshots, events), authorizer);
}

describe("EmotionService persisted replay", () => {
  it("queries an arbitrary historical date with coexisting versions", async () => {
    const result = await service().snapshots({ date: "2026-08-13" });
    expect(result.map((item) => item.algorithmVersion)).toEqual([
      "emotion_score_v1",
      "emotion_score_v2",
    ]);
  });

  it("filters by algorithm version and sector", async () => {
    const selected = await service().snapshots({
      date: "2026-08-13",
      algorithmVersion: "emotion_score_v2",
    });
    expect(selected.map((item) => item.score)).toEqual([0.45]);
    const rotation = await service().rotationEvents({
      date: "2026-08-13",
      sectorId: "sector-b",
    });
    expect(rotation).toHaveLength(1);
  });

  it("fails closed when event time precedes asOf but available_time does not", async () => {
    const delayedSnapshot = {
      ...snapshots[0],
      availableTime: "2026-08-13T02:30:00.000Z",
    } as MarketEmotionSnapshot & { availableTime: string };
    const delayedRotation = {
      ...events[0],
      availableTime: "2026-08-13T02:30:00.000Z",
    } as SectorRotationEvent & { availableTime: string };
    const delayedService = new EmotionService(
      new InMemoryEmotionRepository([delayedSnapshot], [delayedRotation]),
    );
    await expect(
      delayedService.snapshots({ date: "2026-08-13", asOf: "2026-08-13T02:00:00.000Z" }),
    ).resolves.toEqual([]);
    await expect(
      delayedService.rotationEvents({
        date: "2026-08-13",
        asOf: "2026-08-13T02:00:00.000Z",
      }),
    ).resolves.toEqual([]);
  });

  it("defaults legacy full-day replay to the selected Shanghai day end", async () => {
    let receivedAsOf = "";
    const repository = {
      querySnapshots: async (query: { asOf: string }) => {
        receivedAsOf = query.asOf;
        return [];
      },
      queryRotationEvents: async () => [],
      listVersions: async () => [],
    };
    await new EmotionService(repository).snapshots({ date: "2026-08-13" });
    expect(receivedAsOf).toBe("2026-08-13T15:59:59.999Z");
  });

  it("validates date and rejects unknown filters", async () => {
    await expect(service().snapshots({ date: "2026-13-40" })).rejects.toThrow(
      EmotionValidationError,
    );
    await expect(service().snapshots({ date: "2026-08-13", rawSql: "DROP" })).rejects.toThrow(
      EmotionValidationError,
    );
    await expect(service().snapshots({ date: "2026-08-13", asOf: "not-a-time" })).rejects.toThrow(
      "asOf must be an ISO-8601 timestamp",
    );
    await expect(
      service().snapshots({ date: "2026-08-13", asOf: "2026-08-13T15:00:00" }),
    ).rejects.toThrow("asOf must be an ISO-8601 timestamp");
    await expect(
      service().snapshots({ date: "2026-08-13", asOf: "2026-02-30T00:00:00Z" }),
    ).rejects.toThrow("asOf must be an ISO-8601 timestamp");
  });

  it("lists all persisted algorithm versions", async () => {
    await expect(service().versions()).resolves.toEqual([
      "emotion_score_v1",
      "emotion_score_v2",
      "rotation_event_v2",
    ]);
  });

  it("returns a controlled forbidden response", async () => {
    await expect(service(denyAll).snapshots({ date: "2026-08-13" })).rejects.toThrow(
      ForbiddenException,
    );
  });

  it("propagates repository failure rather than fabricating empty history", async () => {
    const repository = {
      querySnapshots: async () => {
        throw new Error("ClickHouse unavailable");
      },
      queryRotationEvents: async () => [],
      listVersions: async () => [],
    };
    await expect(new EmotionService(repository).snapshots({ date: "2026-08-13" })).rejects.toThrow(
      "ClickHouse unavailable",
    );
  });
});
