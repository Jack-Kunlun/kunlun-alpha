import { describe, expect, it } from "vitest";

import { ConflictException } from "@nestjs/common";
import { computeCandidateIdFromPayload, computeCandidateRevisionIdFromPayload } from "@kunlun/contracts/kol";
import { InMemoryClaimReviewRepository } from "./in-memory-claim-review.repository";
import { ClaimCandidateMaterializer } from "./claim-candidate-materializer";
import { ClaimReviewService } from "./claim-review.service";
import { validateClaimReview } from "./claim-review-validation";

function candidatePayload(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    schemaVersion: "claim-extraction-candidate-v1",
    candidateId: "candidate-1",
    revisionId: "revision-1",
    previousRevisionId: null,
    semanticLabel: "PUBLIC_SPEECH_CANDIDATE_NOT_FACT_OR_EXECUTION",
    statement: "公开表述",
    action: "BUY",
    polarity: "AFFIRMED",
    conditionality: "UNCONDITIONAL",
    statementKind: "DIRECT",
    attribution: "SELF",
    eventTimeStatus: "UNKNOWN",
    eventTime: null,
    eventDate: null,
    instrumentId: "600519.SH",
    anchors: [{
      anchorType: "CONTENT",
      sourceIndex: 0,
      contentId: "content-1",
      contentVersion: "v1",
      contentRevisionId: "content-r1",
      contentAvailableTime: "2025-01-01T00:00:00Z",
      source: "test",
      sourceVersion: "v1",
      startOffset: 0,
      endOffset: 4,
      excerpt: "公开表述",
      evidenceGrade: "PRIMARY_SOURCE",
      evidenceGradeVersion: "evidence-grade-v1",
    }],
    evidenceGrade: "PRIMARY_SOURCE",
    evidenceGradeVersion: "evidence-grade-v1",
    confidenceBps: 8000,
    source: "kol-claim-extractor",
    sourceVersion: "v1",
    algorithmVersion: "kol-claim-extraction-v1",
    promptVersion: "prompt-v1",
    modelProvider: "fake",
    modelVersion: "v1",
    configurationFingerprint: "a".repeat(64),
    policyFingerprint: "b".repeat(64),
    recognitionRunId: "run-1",
    publishTime: "2025-01-01T00:00:00Z",
    ingestTime: "2025-01-01T00:00:00Z",
    processingTime: "2025-01-01T00:00:00Z",
    availableTime: "2025-01-01T00:00:00Z",
    reviewStatus: "UNREVIEWED",
    deleted: false,
    deletedAt: null,
    deletionReason: null,
    ...overrides,
  };
  const requestedCandidateId = overrides.candidateId;
  const candidateId = requestedCandidateId ?? computeCandidateIdFromPayload(payload);
  const withCandidateId = { ...payload, candidateId };
  return {
    ...withCandidateId,
    candidateId: requestedCandidateId ?? candidateId,
    revisionId: computeCandidateRevisionIdFromPayload(withCandidateId),
  };
}

describe("ClaimReviewService", () => {
  it("has a server-owned review boundary", () => {
    expect(ClaimReviewService).toBeDefined();
  });

  it("owns reviewer/time and rejects a changed replay under the same client key", async () => {
    const repository = new InMemoryClaimReviewRepository();
    const root = candidatePayload();
    await new ClaimCandidateMaterializer(repository).materialize(root);
    const service = new ClaimReviewService(
      repository,
      { currentReviewerRef: async () => "reviewer-from-auth" },
      { now: () => new Date("2025-01-01T01:00:00.000Z") },
    );
    const submission = {
      schemaVersion: "claim-review-submission-v1",
      clientRequestId: "client-request-1",
      candidateId: root.candidateId,
      candidateRevisionId: root.revisionId,
      decision: "APPROVED",
      reason: "人工审核公开措辞",
    };
    const first = await service.submit(submission);
    const replay = await service.submit(submission);
    expect(replay.reviewId).toBe(first.reviewId);
    expect(first.reviewerRef).toBe("reviewer-from-auth");
    expect(first.createdAt).toBe("2025-01-01T01:00:00.000Z");
    await expect(service.submit({ ...submission, reason: "改写审核理由" })).rejects.toBeInstanceOf(ConflictException);
  });

  it("does not trust a client projection integrity flag", async () => {
    const repository = new InMemoryClaimReviewRepository();
    await expect(new ClaimCandidateMaterializer(repository).materialize(candidatePayload({ integrityValid: false }))).rejects.toThrow();
    await expect(new ClaimCandidateMaterializer(repository).materialize(candidatePayload({ integrityValid: true }))).rejects.toThrow();
  });

  it("rejects a materialized candidate whose canonical identity was altered", async () => {
    const repository = new InMemoryClaimReviewRepository();
    await expect(new ClaimCandidateMaterializer(repository).materialize(candidatePayload({ candidateId: "candidate-2" }))).rejects.toThrow();
  });

  it("replays the durable review after a later candidate tombstone", async () => {
    const repository = new InMemoryClaimReviewRepository();
    const materializer = new ClaimCandidateMaterializer(repository);
    const root = candidatePayload();
    await materializer.materialize(root);
    let currentTime = new Date("2025-01-01T01:00:00.000Z");
    const service = new ClaimReviewService(
      repository,
      { currentReviewerRef: async () => "reviewer-from-auth" },
      { now: () => currentTime },
    );
    const submission = {
      schemaVersion: "claim-review-submission-v1",
      clientRequestId: "client-request-replay-after-tombstone",
      candidateId: root.candidateId,
      candidateRevisionId: root.revisionId,
      decision: "APPROVED",
      reason: "公开措辞已审核",
    };
    const first = await service.submit(submission);
    await materializer.materialize(candidatePayload({
      previousRevisionId: root.revisionId,
      availableTime: "2025-01-01T02:00:00Z",
      deleted: true,
      deletedAt: "2025-01-01T03:00:00Z",
      deletionReason: "source_corrected",
    }));
    currentTime = new Date("2025-01-01T04:00:00.000Z");
    const replay = await service.submit(submission);
    expect(replay).toEqual(first);
    await expect(service.submit({ ...submission, reason: "篡改后的重放" })).rejects.toBeInstanceOf(ConflictException);
    await expect(service.submit({ ...submission, clientRequestId: "fresh-stale-request" })).rejects.toBeInstanceOf(ConflictException);
  });

  it("rejects review of a superseded candidate head", async () => {
    const repository = new InMemoryClaimReviewRepository();
    const materializer = new ClaimCandidateMaterializer(repository);
    const root = candidatePayload();
    await materializer.materialize(root);
    await materializer.materialize(candidatePayload({
      previousRevisionId: root.revisionId,
      availableTime: "2025-01-01T02:00:00Z",
      deleted: true,
      deletedAt: "2025-01-01T02:00:00Z",
      deletionReason: "source_corrected",
    }));
    const service = new ClaimReviewService(
      repository,
      { currentReviewerRef: async () => "reviewer-from-auth" },
      { now: () => new Date("2025-01-01T03:00:00.000Z") },
    );
    await expect(service.submit({
      schemaVersion: "claim-review-submission-v1",
      clientRequestId: "client-request-old",
      candidateId: root.candidateId,
      candidateRevisionId: root.revisionId,
      decision: "APPROVED",
      reason: "旧版本",
    })).rejects.toBeInstanceOf(ConflictException);
  });

  it("rechecks the candidate head atomically during append", async () => {
    const repository = new InMemoryClaimReviewRepository();
    const materializer = new ClaimCandidateMaterializer(repository);
    const root = candidatePayload();
    await materializer.materialize(root);
    const append = repository.appendReview.bind(repository);
    repository.appendReview = async (review, expectedPreviousReviewId) => {
      await materializer.materialize(candidatePayload({
        previousRevisionId: root.revisionId,
        processingTime: "2025-01-01T02:00:00Z",
        availableTime: "2025-01-01T02:00:00Z",
        recognitionRunId: "interleaved-successor",
      }));
      return append(review, expectedPreviousReviewId);
    };
    const service = new ClaimReviewService(
      repository,
      { currentReviewerRef: async () => "reviewer-from-auth" },
      { now: () => new Date("2025-01-01T03:00:00.000Z") },
    );

    await expect(service.submit({
      schemaVersion: "claim-review-submission-v1",
      clientRequestId: "client-request-interleaved",
      candidateId: root.candidateId,
      candidateRevisionId: root.revisionId,
      decision: "APPROVED",
      reason: "并发审核",
    })).rejects.toBeInstanceOf(ConflictException);
  });

  it("uses strict microsecond RFC3339 validation for persisted reviews", () => {
    const base = {
      schemaVersion: "claim-review-v1",
      reviewId: "review-strict-time",
      candidateId: "candidate-strict-time",
      candidateRevisionId: "revision-strict-time",
      decision: "APPROVED",
      reason: "严格时间",
      comment: null,
      reviewerRef: "trusted-reviewer",
      createdAt: "2025-01-01T00:00:00.123456Z",
      availableAt: "2025-01-01T00:00:00.123457Z",
      submissionFingerprint: "f".repeat(64),
      previousReviewId: null,
      reviewMeaning: "PUBLIC_WORDING_REVIEWED_NOT_FACT_OR_EXECUTION",
    };
    expect(validateClaimReview(base).availableAt).toBe(base.availableAt);
    expect(() => validateClaimReview({ ...base, createdAt: "2025-02-30T00:00:00Z" })).toThrow(/valid timezone-aware RFC3339/);
    expect(() => validateClaimReview({ ...base, createdAt: "2025-01-01T00:00:00.123458Z" })).toThrow(/createdAt/);
  });
});
