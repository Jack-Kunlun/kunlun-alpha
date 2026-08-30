import { createHash } from "node:crypto";
import {
  compareClaimExtractionInstants,
  computeCandidateIdFromPayload,
  computeCandidateRevisionIdFromPayload,
  computeClaimExtractionCandidatePayloadFingerprint,
  parseClaimExtractionCandidatePayload,
} from "@kunlun/contracts/kol";
import type { KolClaimReview } from "@kunlun/shared-types";
import type {
  AppendClaimReviewResult,
  ClaimCandidateProjection,
  ClaimCandidateProjectionStore,
  ClaimReviewRepository,
} from "./claim-review-repository";

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === "object") {
    const input = value as Record<string, unknown>;
    return Object.fromEntries(
      Object.keys(input)
        .sort()
        .map((key) => [key, canonical(input[key])]),
    );
  }
  return value;
}

function fingerprint(value: unknown): string {
  return createHash("sha256")
    .update(JSON.stringify(canonical(value)), "utf8")
    .digest("hex");
}

function sameInstant(left: string | null, right: string | null): boolean {
  if (left === null || right === null) return left === right;
  return compareClaimExtractionInstants(left, right) === 0;
}

function verifyProjection(value: ClaimCandidateProjection): ClaimCandidateProjection {
  const payload = parseClaimExtractionCandidatePayload(value.canonicalPayload) as Record<
    string,
    unknown
  >;
  if (
    payload.candidateId !== value.candidateId ||
    payload.revisionId !== value.revisionId ||
    payload.previousRevisionId !== value.previousRevisionId
  )
    throw new Error("candidate projection identity conflict");
  if (
    computeCandidateIdFromPayload(payload) !== value.candidateId ||
    computeCandidateRevisionIdFromPayload(payload) !== value.revisionId
  )
    throw new Error("candidate projection canonical identity conflict");
  if (
    !sameInstant(payload.availableTime as string, value.availableAt) ||
    payload.deleted !== value.deleted ||
    payload.confidenceBps !== value.confidenceBps ||
    !sameInstant(payload.deletedAt as string | null, value.deletedAt) ||
    payload.deletionReason !== value.deletionReason
  )
    throw new Error("candidate projection field conflict");
  const payloadFingerprint = computeClaimExtractionCandidatePayloadFingerprint(payload);
  const integrityFingerprint = fingerprint({
    algorithmVersion: payload.algorithmVersion,
    payloadFingerprint,
  });
  if (
    payloadFingerprint !== value.payloadFingerprint ||
    integrityFingerprint !== value.integrityFingerprint
  )
    throw new Error("candidate projection fingerprint conflict");
  return {
    ...value,
    availableAt: payload.availableTime as string,
    deletedAt: payload.deletedAt as string | null,
    canonicalPayload: payload,
  };
}

function sameCandidate(left: ClaimCandidateProjection, right: ClaimCandidateProjection): boolean {
  return (
    left.candidateId === right.candidateId &&
    left.revisionId === right.revisionId &&
    left.previousRevisionId === right.previousRevisionId &&
    sameInstant(left.availableAt, right.availableAt) &&
    left.deleted === right.deleted &&
    sameInstant(left.deletedAt, right.deletedAt) &&
    left.deletionReason === right.deletionReason &&
    left.confidenceBps === right.confidenceBps &&
    left.integrityFingerprint === right.integrityFingerprint &&
    left.payloadFingerprint === right.payloadFingerprint &&
    computeClaimExtractionCandidatePayloadFingerprint(left.canonicalPayload) ===
      computeClaimExtractionCandidatePayloadFingerprint(right.canonicalPayload)
  );
}

export class InMemoryClaimReviewRepository
  implements ClaimReviewRepository, ClaimCandidateProjectionStore
{
  private readonly candidates = new Map<string, ClaimCandidateProjection>();
  private readonly reviews = new Map<string, KolClaimReview[]>();

  private key(candidateId: string, revisionId: string): string {
    return `${candidateId}\u001f${revisionId}`;
  }

  private copyCandidate(candidate: ClaimCandidateProjection): ClaimCandidateProjection {
    return {
      ...candidate,
      canonicalPayload: JSON.parse(JSON.stringify(candidate.canonicalPayload)) as Readonly<
        Record<string, unknown>
      >,
    };
  }

  private candidateHead(
    candidateId: string,
    decisionTime?: string,
  ): ClaimCandidateProjection | null {
    const chain = [...this.candidates.values()].filter(
      (item) =>
        item.candidateId === candidateId &&
        (decisionTime === undefined ||
          compareClaimExtractionInstants(
            item.deleted ? (item.deletedAt ?? item.availableAt) : item.availableAt,
            decisionTime,
          ) <= 0),
    );
    if (chain.length === 0) return null;
    const childRevisions = new Set(
      chain.flatMap((item) => (item.previousRevisionId === null ? [] : [item.previousRevisionId])),
    );
    const heads = chain.filter((item) => !childRevisions.has(item.revisionId));
    if (heads.length !== 1) throw new Error("candidate projection has no unique head");
    return heads[0] ?? null;
  }

  async storeCandidateProjection(candidate: ClaimCandidateProjection): Promise<void> {
    const verified = verifyProjection(candidate);
    const key = this.key(verified.candidateId, verified.revisionId);
    const existing = this.candidates.get(key);
    if (existing && !sameCandidate(existing, verified))
      throw new Error("candidate projection conflict");
    if (existing) return;
    const chain = [...this.candidates.values()].filter(
      (item) => item.candidateId === verified.candidateId,
    );
    if (verified.previousRevisionId === null && chain.length > 0)
      throw new Error("candidate root conflict");
    if (verified.previousRevisionId !== null) {
      const predecessor = chain.find((item) => item.revisionId === verified.previousRevisionId);
      if (!predecessor) throw new Error("candidate predecessor conflict");
      if (this.candidateHead(verified.candidateId)?.revisionId !== predecessor.revisionId)
        throw new Error("candidate predecessor is not current head");
      if (chain.some((item) => item.previousRevisionId === verified.previousRevisionId))
        throw new Error("candidate fork conflict");
      if (compareClaimExtractionInstants(verified.availableAt, predecessor.availableAt) <= 0)
        throw new Error("candidate availability must increase");
    }
    this.candidates.set(key, this.copyCandidate(verified));
  }

  async findCandidate(
    candidateId: string,
    revisionId: string,
  ): Promise<ClaimCandidateProjection | null> {
    const candidate = this.candidates.get(this.key(candidateId, revisionId));
    return candidate ? this.copyCandidate(candidate) : null;
  }

  async latestCandidate(
    candidateId: string,
    decisionTime: string,
  ): Promise<ClaimCandidateProjection | null> {
    const candidate = this.candidateHead(candidateId, decisionTime);
    return candidate && !candidate.deleted ? this.copyCandidate(candidate) : null;
  }

  async latestReview(candidateId: string, revisionId: string): Promise<KolClaimReview | null> {
    const reviews = this.reviews.get(this.key(candidateId, revisionId));
    if (!reviews || reviews.length === 0) return null;
    const childIds = new Set(
      reviews.flatMap((item) => (item.previousReviewId === null ? [] : [item.previousReviewId])),
    );
    const heads = reviews.filter((item) => !childIds.has(item.reviewId));
    if (heads.length !== 1) throw new Error("review chain has no unique head");
    return heads[0] ?? null;
  }

  async findReviewById(reviewId: string): Promise<KolClaimReview | null> {
    for (const chain of this.reviews.values()) {
      const found = chain.find((item) => item.reviewId === reviewId);
      if (found) return found;
    }
    return null;
  }

  async appendReview(
    review: KolClaimReview,
    expectedPreviousReviewId: string | null,
  ): Promise<AppendClaimReviewResult> {
    const currentCandidate = this.candidateHead(review.candidateId, review.availableAt);
    if (
      currentCandidate === null ||
      currentCandidate.deleted ||
      currentCandidate.revisionId !== review.candidateRevisionId
    )
      throw new Error("candidate current projection conflict");
    const key = this.key(review.candidateId, review.candidateRevisionId);
    const chain = this.reviews.get(key) ?? [];
    const sameReviewId = chain.find((item) => item.reviewId === review.reviewId);
    if (sameReviewId) {
      if (
        sameReviewId.submissionFingerprint !== review.submissionFingerprint ||
        sameReviewId.candidateId !== review.candidateId ||
        sameReviewId.candidateRevisionId !== review.candidateRevisionId ||
        sameReviewId.decision !== review.decision ||
        sameReviewId.reason !== review.reason ||
        sameReviewId.comment !== review.comment ||
        sameReviewId.reviewerRef !== review.reviewerRef
      )
        throw new Error("review identity conflict");
      return { disposition: "EXISTING", review: sameReviewId };
    }
    const existing = chain.find(
      (item) => item.submissionFingerprint === review.submissionFingerprint,
    );
    if (existing) {
      if (
        existing.reviewId !== review.reviewId ||
        JSON.stringify(existing) !== JSON.stringify(review)
      )
        throw new Error("review fingerprint conflict");
      return { disposition: "EXISTING", review: existing };
    }
    const childIds = new Set(
      chain.flatMap((item) => (item.previousReviewId === null ? [] : [item.previousReviewId])),
    );
    const heads = chain.filter((item) => !childIds.has(item.reviewId));
    if (heads.length > 1) throw new Error("review chain has no unique head");
    const previous = heads[0]?.reviewId ?? null;
    if (
      previous !== expectedPreviousReviewId ||
      review.previousReviewId !== expectedPreviousReviewId
    )
      throw new Error("review predecessor conflict");
    chain.push(review);
    this.reviews.set(key, chain);
    return { disposition: "INSERTED", review };
  }
}
