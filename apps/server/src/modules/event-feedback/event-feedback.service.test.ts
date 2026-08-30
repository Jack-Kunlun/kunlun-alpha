import { ConflictException, ForbiddenException } from "@nestjs/common";
import { describe, expect, it } from "vitest";
import type { EventFeedbackAuthorizer } from "./event-feedback-authorizer";
import { InMemoryEventFeedbackRepository } from "./in-memory-event-feedback.repository";
import { type EventFeedbackClock, EventFeedbackService } from "./event-feedback.service";

const EVENT_ID = "a".repeat(64);
const CONFIG = "b".repeat(64);
const NOW = new Date("2026-08-24T06:00:00.000Z");
const allow: EventFeedbackAuthorizer = { currentReviewerRef: async () => "reviewer-7" };
const deny: EventFeedbackAuthorizer = { currentReviewerRef: async () => null };
const clock: EventFeedbackClock = { now: () => NOW };

function submission(clientRequestId = "request-1") {
  return {
    schemaVersion: "event-feedback-submission-v1",
    clientRequestId,
    eventId: EVENT_ID,
    modelConfigurationFingerprint: CONFIG,
    action: "CONFIRM",
    reasonCode: "ACCURATE",
  };
}

describe("EventFeedbackService", () => {
  it("appends feedback with server-owned reviewer, time and fingerprints", async () => {
    const service = new EventFeedbackService(new InMemoryEventFeedbackRepository(), allow, clock);
    const result = await service.submit(submission());
    expect(result.schemaVersion).toBe("event-feedback-v1");
    expect(result.reviewerRef).toBe("reviewer-7");
    expect(result.createdAt).toBe(NOW.toISOString());
    expect(result.availableAt).toBe(NOW.toISOString());
    expect(result.feedbackId).toMatch(/^[0-9a-f]{64}$/);
    expect(result.submissionFingerprint).toMatch(/^[0-9a-f]{64}$/);
  });

  it("is idempotent for an exact retry", async () => {
    const repository = new InMemoryEventFeedbackRepository();
    const service = new EventFeedbackService(repository, allow, clock);
    const first = await service.submit(submission());
    const second = await service.submit(submission());
    expect(second).toEqual(first);
    await expect(service.list({ limit: "100" })).resolves.toHaveLength(1);
  });

  it("rejects reuse of a client request id with different feedback", async () => {
    const service = new EventFeedbackService(new InMemoryEventFeedbackRepository(), allow, clock);
    await service.submit(submission());
    await expect(
      service.submit({ ...submission(), action: "REJECT", reasonCode: "NOT_MARKET_EVENT" }),
    ).rejects.toThrow(ConflictException);
  });

  it("requires a structured correction only for CORRECT", async () => {
    const service = new EventFeedbackService(new InMemoryEventFeedbackRepository(), allow, clock);
    await expect(
      service.submit({ ...submission(), action: "CORRECT", reasonCode: "WRONG_ENTITY" }),
    ).rejects.toThrow("requires correction");
    const corrected = await service.submit({
      ...submission("request-2"),
      action: "CORRECT",
      reasonCode: "WRONG_ENTITY",
      correction: { instrumentIds: ["000001.SZ"] },
    });
    expect(corrected.correction?.instrumentIds).toEqual(["000001.SZ"]);
  });

  it("rejects unknown fields and noncanonical instruments", async () => {
    const service = new EventFeedbackService(new InMemoryEventFeedbackRepository(), allow, clock);
    await expect(service.submit({ ...submission(), reviewerRef: "forged" })).rejects.toThrow(
      "unknown feedback field",
    );
    await expect(
      service.submit({
        ...submission(),
        action: "CORRECT",
        reasonCode: "WRONG_ENTITY",
        correction: { instrumentIds: ["SH.600519"] },
      }),
    ).rejects.toThrow("instrumentIds");
  });

  it("fails closed when no authenticated reviewer is available", async () => {
    const service = new EventFeedbackService(new InMemoryEventFeedbackRepository(), deny, clock);
    await expect(service.submit(submission())).rejects.toThrow(ForbiddenException);
    await expect(service.list({})).rejects.toThrow(ForbiddenException);
  });
});
