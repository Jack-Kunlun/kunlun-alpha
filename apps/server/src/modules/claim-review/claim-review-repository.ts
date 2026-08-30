import type { KolClaimReview } from "@kunlun/shared-types";

export interface ClaimCandidateProjection {
  candidateId: string;
  revisionId: string;
  previousRevisionId: string | null;
  availableAt: string;
  deleted: boolean;
  deletedAt: string | null;
  deletionReason: string | null;
  confidenceBps: number;
  integrityFingerprint: string;
  payloadFingerprint: string;
  canonicalPayload: Readonly<Record<string, unknown>>;
}

export interface AppendClaimReviewResult {
  disposition: "INSERTED" | "EXISTING";
  review: KolClaimReview;
}

export interface ClaimReviewRepository {
  findCandidate(candidateId: string, revisionId: string): Promise<ClaimCandidateProjection | null>;
  latestCandidate(
    candidateId: string,
    decisionTime: string,
  ): Promise<ClaimCandidateProjection | null>;
  latestReview(candidateId: string, revisionId: string): Promise<KolClaimReview | null>;
  findReviewById(reviewId: string): Promise<KolClaimReview | null>;
  appendReview(
    review: KolClaimReview,
    expectedPreviousReviewId: string | null,
  ): Promise<AppendClaimReviewResult>;
}

/** Internal server-owned projection sink; no controller exposes candidate upsert. */
export interface ClaimCandidateProjectionStore {
  storeCandidateProjection(candidate: ClaimCandidateProjection): Promise<void>;
}
