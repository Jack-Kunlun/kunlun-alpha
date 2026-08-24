import type { EventFeedback } from "@kunlun/shared-types";
import type { Pool } from "pg";
import { describe, expect, it } from "vitest";
import { PostgresEventFeedbackRepository } from "./postgres-event-feedback.repository";

const feedback: EventFeedback = {
  schemaVersion: "event-feedback-v1",
  feedbackId: "a".repeat(64),
  clientRequestId: "request-1",
  eventId: "b".repeat(64),
  modelConfigurationFingerprint: "c".repeat(64),
  action: "CONFIRM",
  reasonCode: "ACCURATE",
  reviewerRef: "reviewer-1",
  submissionFingerprint: "d".repeat(64),
  createdAt: "2026-08-24T06:00:00.000Z",
  availableAt: "2026-08-24T06:00:00.000Z",
};

function row() {
  return {
    feedback_id: feedback.feedbackId,
    client_request_id: feedback.clientRequestId,
    event_id: feedback.eventId,
    model_configuration_fingerprint: feedback.modelConfigurationFingerprint,
    action: feedback.action,
    reason_code: feedback.reasonCode,
    correction: null,
    comment: null,
    reviewer_ref: feedback.reviewerRef,
    submission_fingerprint: feedback.submissionFingerprint,
    created_at: feedback.createdAt,
    available_at: feedback.availableAt,
  };
}

describe("PostgresEventFeedbackRepository", () => {
  it("parameterizes append values and returns validated rows", async () => {
    const calls: Array<{ sql: string; params: unknown[] }> = [];
    const pool = {
      query: async (sql: string, params: unknown[]) => {
        calls.push({ sql, params });
        return { rows: [row()] };
      },
    } as unknown as Pool;
    const repository = new PostgresEventFeedbackRepository(pool);
    const result = await repository.append({ ...feedback, comment: "'); DROP TABLE event_feedback; --" });
    expect(result.disposition).toBe("INSERTED");
    expect(calls[0]?.sql).not.toContain("DROP TABLE");
    expect(calls[0]?.params).toContain("'); DROP TABLE event_feedback; --");
  });

  it("uses bounded parameterized list filters", async () => {
    const calls: Array<{ sql: string; params: unknown[] }> = [];
    const pool = {
      query: async (sql: string, params: unknown[]) => {
        calls.push({ sql, params });
        return { rows: [row()] };
      },
    } as unknown as Pool;
    const repository = new PostgresEventFeedbackRepository(pool);
    await repository.list({ eventId: feedback.eventId, limit: 20 });
    expect(calls[0]?.params).toEqual([feedback.eventId, null, 20]);
  });
});
