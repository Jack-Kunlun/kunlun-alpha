import { ConflictException, ForbiddenException, Inject, Injectable, NotFoundException } from "@nestjs/common";
import { compareClaimExtractionInstants } from "@kunlun/contracts/kol";
import type { KolClaimReview, KolClaimReviewSubmission } from "@kunlun/shared-types";
import { createHash } from "node:crypto";
import { DenyAllClaimReviewAuthorizer, type ClaimReviewAuthorizer } from "./claim-review-authorizer";
import type { ClaimReviewRepository } from "./claim-review-repository";
import { CLAIM_REVIEW_AUTHORIZER, CLAIM_REVIEW_CLOCK, CLAIM_REVIEW_REPOSITORY } from "./claim-review.tokens";
import { validateClaimReviewSubmission } from "./claim-review-validation";

export interface ClaimReviewClock { now(): Date; }
export class SystemClaimReviewClock implements ClaimReviewClock { now(): Date { return new Date(); } }
function digest(value: unknown): string { return createHash("sha256").update(JSON.stringify(value), "utf8").digest("hex"); }

@Injectable()
export class ClaimReviewService {
  constructor(@Inject(CLAIM_REVIEW_REPOSITORY) private readonly repository: ClaimReviewRepository, @Inject(CLAIM_REVIEW_AUTHORIZER) private readonly authorizer: ClaimReviewAuthorizer = new DenyAllClaimReviewAuthorizer(), @Inject(CLAIM_REVIEW_CLOCK) private readonly clock: ClaimReviewClock = new SystemClaimReviewClock()) {}

  async submit(value: unknown): Promise<KolClaimReview> {
    const reviewerRef = await this.authorizer.currentReviewerRef();
    if (reviewerRef === null) throw new ForbiddenException("无权审核公开表述");
    const submission: KolClaimReviewSubmission = validateClaimReviewSubmission(value);
    const now = this.clock.now();
    if (Number.isNaN(now.getTime())) throw new ConflictException("server clock is invalid");
    const submissionFingerprint = digest({ candidateId: submission.candidateId, candidateRevisionId: submission.candidateRevisionId, clientRequestId: submission.clientRequestId, comment: submission.comment ?? null, decision: submission.decision, expectedPreviousReviewId: submission.expectedPreviousReviewId ?? null, reason: submission.reason, reviewerRef });
    const reviewId = digest({ candidateId: submission.candidateId, candidateRevisionId: submission.candidateRevisionId, clientRequestId: submission.clientRequestId, reviewerRef });
    const existingReview = await this.repository.findReviewById(reviewId);
    if (existingReview !== null) {
      if (existingReview.submissionFingerprint !== submissionFingerprint || existingReview.candidateId !== submission.candidateId || existingReview.candidateRevisionId !== submission.candidateRevisionId || existingReview.decision !== submission.decision || existingReview.reason !== submission.reason || existingReview.comment !== (submission.comment ?? null) || existingReview.reviewerRef !== reviewerRef) throw new ConflictException("clientRequestId/review identity conflict");
      return existingReview;
    }
    const candidate = await this.repository.findCandidate(submission.candidateId, submission.candidateRevisionId);
    if (candidate === null) throw new NotFoundException("candidate revision not found");
    const currentCandidate = await this.repository.latestCandidate(submission.candidateId, now.toISOString());
    if (currentCandidate === null || currentCandidate.revisionId !== candidate.revisionId) throw new ConflictException("candidate revision is not current");
    if (candidate.deleted || candidate.confidenceBps < 0 || compareClaimExtractionInstants(candidate.availableAt, now.toISOString()) > 0) throw new ConflictException("candidate is unavailable for review");
    const previous = await this.repository.latestReview(candidate.candidateId, candidate.revisionId);
    const previousId = previous?.reviewId ?? null;
    if (submission.expectedPreviousReviewId !== undefined && submission.expectedPreviousReviewId !== previousId) throw new ConflictException("review predecessor does not match server latest");
    const review: KolClaimReview = { schemaVersion: "claim-review-v1", reviewId, candidateId: submission.candidateId, candidateRevisionId: submission.candidateRevisionId, decision: submission.decision, reason: submission.reason, comment: submission.comment ?? null, reviewerRef, createdAt: now.toISOString(), availableAt: now.toISOString(), submissionFingerprint, previousReviewId: previousId, reviewMeaning: "PUBLIC_WORDING_REVIEWED_NOT_FACT_OR_EXECUTION" };
    let result: Awaited<ReturnType<ClaimReviewRepository["appendReview"]>>;
    try {
      result = await this.repository.appendReview(review, previousId);
    } catch (error) {
      if (error instanceof Error && /conflict|predecessor|unique/i.test(error.message)) throw new ConflictException("review append conflict");
      throw error;
    }
    if (result.disposition === "EXISTING" && result.review.submissionFingerprint !== submissionFingerprint) throw new ConflictException("clientRequestId/review identity conflict");
    return result.review;
  }
}
