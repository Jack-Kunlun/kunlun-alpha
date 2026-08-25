import { compareClaimExtractionInstants } from "@kunlun/contracts/kol";
import type { KolClaimReview, KolClaimReviewSubmission } from "@kunlun/shared-types";

const HEX_64 = /^[0-9a-f]{64}$/;
const ID = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$/;
const DECISIONS = new Set(["IN_REVIEW", "APPROVED", "REJECTED"]);
const SUBMISSION_KEYS = new Set(["schemaVersion", "clientRequestId", "candidateId", "candidateRevisionId", "decision", "reason", "comment", "expectedPreviousReviewId"]);

export class ClaimReviewValidationError extends Error {}

function object(value: unknown, name: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new ClaimReviewValidationError(`${name} must be an object`);
  return value as Record<string, unknown>;
}

function id(value: unknown, field: string): string {
  if (typeof value !== "string" || !ID.test(value)) throw new ClaimReviewValidationError(`${field} is invalid`);
  return value;
}

function text(value: unknown, field: string, maximum: number): string {
  if (typeof value !== "string" || value.length < 1 || value.length > maximum) throw new ClaimReviewValidationError(`${field} is invalid`);
  return value;
}

function instant(value: unknown, field: string): string {
  if (typeof value !== "string") throw new ClaimReviewValidationError(`${field} must be timezone-aware`);
  try {
    compareClaimExtractionInstants(value, value);
  } catch {
    throw new ClaimReviewValidationError(`${field} must be a valid timezone-aware RFC3339 instant`);
  }
  return value;
}

export function validateClaimReviewSubmission(value: unknown): KolClaimReviewSubmission {
  const input = object(value, "claim review submission");
  for (const key of Object.keys(input)) if (!SUBMISSION_KEYS.has(key)) throw new ClaimReviewValidationError(`unknown review submission field: ${key}`);
  if (input.schemaVersion !== "claim-review-submission-v1") throw new ClaimReviewValidationError("unsupported review submission schema");
  const comment = input.comment === undefined || input.comment === null ? null : text(input.comment, "comment", 4000);
  const previous = input.expectedPreviousReviewId === undefined || input.expectedPreviousReviewId === null ? null : id(input.expectedPreviousReviewId, "expectedPreviousReviewId");
  if (typeof input.decision !== "string" || !DECISIONS.has(input.decision)) throw new ClaimReviewValidationError("decision is invalid");
  return { schemaVersion: "claim-review-submission-v1", clientRequestId: id(input.clientRequestId, "clientRequestId"), candidateId: id(input.candidateId, "candidateId"), candidateRevisionId: id(input.candidateRevisionId, "candidateRevisionId"), decision: input.decision as KolClaimReviewSubmission["decision"], reason: text(input.reason, "reason", 1000), ...(comment === null ? {} : { comment }), ...(previous === null ? {} : { expectedPreviousReviewId: previous }) };
}

export function validateClaimReview(value: unknown): KolClaimReview {
  const input = object(value, "claim review");
  const expected = new Set(["schemaVersion", "reviewId", "candidateId", "candidateRevisionId", "decision", "reason", "comment", "reviewerRef", "createdAt", "availableAt", "submissionFingerprint", "previousReviewId", "reviewMeaning"]);
  for (const key of Object.keys(input)) if (!expected.has(key)) throw new ClaimReviewValidationError(`unknown review field: ${key}`);
  if (input.schemaVersion !== "claim-review-v1" || input.reviewMeaning !== "PUBLIC_WORDING_REVIEWED_NOT_FACT_OR_EXECUTION") throw new ClaimReviewValidationError("invalid review contract");
  if (typeof input.decision !== "string" || !DECISIONS.has(input.decision)) throw new ClaimReviewValidationError("decision is invalid");
  const created = instant(input.createdAt, "createdAt"); const available = instant(input.availableAt, "availableAt");
  if (compareClaimExtractionInstants(created, available) > 0) throw new ClaimReviewValidationError("createdAt must be <= availableAt");
  if (typeof input.submissionFingerprint !== "string" || !HEX_64.test(input.submissionFingerprint)) throw new ClaimReviewValidationError("submissionFingerprint is invalid");
  const comment = input.comment === null ? null : text(input.comment, "comment", 4000);
  const previous = input.previousReviewId === null ? null : id(input.previousReviewId, "previousReviewId");
  return { schemaVersion: "claim-review-v1", reviewId: id(input.reviewId, "reviewId"), candidateId: id(input.candidateId, "candidateId"), candidateRevisionId: id(input.candidateRevisionId, "candidateRevisionId"), decision: input.decision as KolClaimReview["decision"], reason: text(input.reason, "reason", 1000), comment, reviewerRef: id(input.reviewerRef, "reviewerRef"), createdAt: created, availableAt: available, submissionFingerprint: input.submissionFingerprint, previousReviewId: previous, reviewMeaning: "PUBLIC_WORDING_REVIEWED_NOT_FACT_OR_EXECUTION" };
}
