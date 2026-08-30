import type { Pool } from "pg";
import type { KolClaimReview } from "@kunlun/shared-types";
import { createHash } from "node:crypto";
import {
  compareClaimExtractionInstants,
  computeCandidateIdFromPayload,
  computeCandidateRevisionIdFromPayload,
  computeClaimExtractionCandidatePayloadFingerprint,
  parseClaimExtractionCandidatePayload,
} from "@kunlun/contracts/kol";
import type {
  AppendClaimReviewResult,
  ClaimCandidateProjection,
  ClaimCandidateProjectionStore,
  ClaimReviewRepository,
} from "./claim-review-repository";
import { validateClaimReview } from "./claim-review-validation";

interface CandidateRow {
  candidate_id: string;
  revision_id: string;
  previous_revision_id: string | null;
  previous_available_at: Date | string | null;
  available_at: Date | string;
  deleted: boolean;
  deleted_at: Date | string | null;
  deletion_reason: string | null;
  confidence_bps: number;
  integrity_fingerprint: string;
  payload_fingerprint: string;
  canonical_payload: Record<string, unknown>;
}

interface ReviewRow {
  review_id: string;
  candidate_id: string;
  candidate_revision_id: string;
  decision: string;
  reason: string;
  comment: string | null;
  reviewer_ref: string;
  created_at: Date | string;
  available_at: Date | string;
  submission_fingerprint: string;
  previous_review_id: string | null;
}

const candidateSelect = [
  "candidate_id",
  "revision_id",
  "previous_revision_id",
  `to_char(previous_available_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS previous_available_at`,
  `to_char(available_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS available_at`,
  "deleted",
  `to_char(deleted_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS deleted_at`,
  "deletion_reason",
  "confidence_bps",
  "integrity_fingerprint",
  "payload_fingerprint",
  "canonical_payload",
].join(", ");
const reviewSelect = [
  "review_id",
  "candidate_id",
  "candidate_revision_id",
  "decision",
  "reason",
  "comment",
  "reviewer_ref",
  `to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS created_at`,
  `to_char(available_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS available_at`,
  "submission_fingerprint",
  "previous_review_id",
].join(", ");

function iso(value: Date | string | null): string | null {
  if (value === null) return null;
  if (value instanceof Date)
    throw new Error("PostgreSQL timestamp reads must preserve textual microseconds");
  return value;
}

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
  return { ...value, canonicalPayload: canonical(payload) as Readonly<Record<string, unknown>> };
}

function candidate(row: CandidateRow): ClaimCandidateProjection {
  const payload = parseClaimExtractionCandidatePayload(row.canonical_payload) as Record<
    string,
    unknown
  >;
  const value: ClaimCandidateProjection = {
    candidateId: row.candidate_id,
    revisionId: row.revision_id,
    previousRevisionId: row.previous_revision_id,
    availableAt: iso(row.available_at) as string,
    deleted: row.deleted,
    deletedAt: iso(row.deleted_at),
    deletionReason: row.deletion_reason,
    confidenceBps: row.confidence_bps,
    integrityFingerprint: row.integrity_fingerprint,
    payloadFingerprint: row.payload_fingerprint,
    canonicalPayload: canonical(payload) as Readonly<Record<string, unknown>>,
  };
  if (
    payload.candidateId !== value.candidateId ||
    payload.revisionId !== value.revisionId ||
    payload.previousRevisionId !== value.previousRevisionId ||
    computeCandidateIdFromPayload(payload) !== value.candidateId ||
    computeCandidateRevisionIdFromPayload(payload) !== value.revisionId ||
    !sameInstant(payload.availableTime as string, value.availableAt) ||
    payload.deleted !== value.deleted ||
    !sameInstant(payload.deletedAt as string | null, value.deletedAt) ||
    payload.deletionReason !== value.deletionReason ||
    payload.confidenceBps !== value.confidenceBps ||
    computeClaimExtractionCandidatePayloadFingerprint(payload) !== value.payloadFingerprint ||
    fingerprint({
      algorithmVersion: payload.algorithmVersion,
      payloadFingerprint: value.payloadFingerprint,
    }) !== value.integrityFingerprint
  )
    throw new Error("candidate projection integrity conflict");
  return value;
}

function review(row: ReviewRow): KolClaimReview {
  return validateClaimReview({
    schemaVersion: "claim-review-v1",
    reviewId: row.review_id,
    candidateId: row.candidate_id,
    candidateRevisionId: row.candidate_revision_id,
    decision: row.decision,
    reason: row.reason,
    comment: row.comment,
    reviewerRef: row.reviewer_ref,
    createdAt: iso(row.created_at),
    availableAt: iso(row.available_at),
    submissionFingerprint: row.submission_fingerprint,
    previousReviewId: row.previous_review_id,
    reviewMeaning: "PUBLIC_WORDING_REVIEWED_NOT_FACT_OR_EXECUTION",
  });
}

function sameReview(left: KolClaimReview, right: KolClaimReview): boolean {
  return [
    "reviewId",
    "candidateId",
    "candidateRevisionId",
    "decision",
    "reason",
    "comment",
    "reviewerRef",
    "submissionFingerprint",
    "reviewMeaning",
  ].every((field) => left[field as keyof KolClaimReview] === right[field as keyof KolClaimReview]);
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

export class PostgresClaimReviewRepository
  implements ClaimReviewRepository, ClaimCandidateProjectionStore
{
  constructor(private readonly pool: Pool) {}

  async storeCandidateProjection(value: ClaimCandidateProjection): Promise<void> {
    const verified = verifyProjection(value);
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      await client.query("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", [
        verified.candidateId,
      ]);
      const existingResult = await client.query<CandidateRow>(
        `SELECT ${candidateSelect} FROM kol_claim_candidate_projection WHERE candidate_id = $1 AND revision_id = $2 FOR UPDATE`,
        [verified.candidateId, verified.revisionId],
      );
      if (existingResult.rows[0]) {
        const existing = candidate(existingResult.rows[0]);
        if (!sameCandidate(existing, verified)) throw new Error("candidate projection conflict");
        await client.query("COMMIT");
        return;
      }
      const chainResult = await client.query<CandidateRow>(
        `SELECT ${candidateSelect} FROM kol_claim_candidate_projection WHERE candidate_id = $1 FOR UPDATE`,
        [verified.candidateId],
      );
      const chain = chainResult.rows;
      let previousAvailableAt: string | null = null;
      if (verified.previousRevisionId === null) {
        if (chain.length !== 0) throw new Error("candidate root conflict");
      } else {
        const predecessor = chain.find((item) => item.revision_id === verified.previousRevisionId);
        if (!predecessor) throw new Error("candidate predecessor conflict");
        const childIds = new Set(
          chain.flatMap((item) =>
            item.previous_revision_id === null ? [] : [item.previous_revision_id],
          ),
        );
        const heads = chain.filter((item) => !childIds.has(item.revision_id));
        if (heads.length !== 1 || heads[0]?.revision_id !== predecessor.revision_id)
          throw new Error("candidate predecessor is not current head");
        previousAvailableAt = iso(predecessor.available_at);
        if (previousAvailableAt === null)
          throw new Error("candidate predecessor availability is missing");
        if (compareClaimExtractionInstants(verified.availableAt, previousAvailableAt) <= 0)
          throw new Error("candidate availability must increase");
      }
      await client.query(
        `INSERT INTO kol_claim_candidate_projection
          (candidate_id, revision_id, previous_revision_id, previous_available_at, available_at, deleted, deleted_at,
           deletion_reason, confidence_bps, integrity_fingerprint, payload_fingerprint, canonical_payload)
         VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)`,
        [
          verified.candidateId,
          verified.revisionId,
          verified.previousRevisionId,
          previousAvailableAt,
          verified.availableAt,
          verified.deleted,
          verified.deletedAt,
          verified.deletionReason,
          verified.confidenceBps,
          verified.integrityFingerprint,
          verified.payloadFingerprint,
          verified.canonicalPayload,
        ],
      );
      await client.query("COMMIT");
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }

  async findCandidate(
    candidateId: string,
    revisionId: string,
  ): Promise<ClaimCandidateProjection | null> {
    const result = await this.pool.query<CandidateRow>(
      `SELECT ${candidateSelect} FROM kol_claim_candidate_projection WHERE candidate_id = $1 AND revision_id = $2`,
      [candidateId, revisionId],
    );
    return result.rows[0] ? candidate(result.rows[0]) : null;
  }

  async latestCandidate(
    candidateId: string,
    decisionTime: string,
  ): Promise<ClaimCandidateProjection | null> {
    const result = await this.pool.query<CandidateRow>(
      `SELECT ${candidateSelect}
       FROM kol_claim_candidate_projection current
       WHERE current.candidate_id = $1
         AND ((current.deleted = FALSE AND current.available_at <= $2) OR (current.deleted = TRUE AND current.deleted_at <= $2))
         AND NOT EXISTS (
           SELECT 1 FROM kol_claim_candidate_projection child
           WHERE child.candidate_id = current.candidate_id
             AND child.previous_revision_id = current.revision_id
             AND ((child.deleted = FALSE AND child.available_at <= $2) OR (child.deleted = TRUE AND child.deleted_at <= $2))
         )
       LIMIT 2`,
      [candidateId, decisionTime],
    );
    if (result.rows.length > 1) throw new Error("candidate projection has no unique head");
    if (!result.rows[0]) return null;
    const head = candidate(result.rows[0]);
    return head.deleted ? null : head;
  }

  async latestReview(candidateId: string, revisionId: string): Promise<KolClaimReview | null> {
    const result = await this.pool.query<ReviewRow>(
      `SELECT ${reviewSelect}
       FROM kol_claim_reviews current
       WHERE current.candidate_id = $1 AND current.candidate_revision_id = $2
         AND NOT EXISTS (
           SELECT 1 FROM kol_claim_reviews child
           WHERE child.candidate_id = current.candidate_id
             AND child.candidate_revision_id = current.candidate_revision_id
             AND child.previous_review_id = current.review_id
         )
       LIMIT 2`,
      [candidateId, revisionId],
    );
    if (result.rows.length > 1) throw new Error("review chain has no unique head");
    return result.rows[0] ? review(result.rows[0]) : null;
  }

  async findReviewById(reviewId: string): Promise<KolClaimReview | null> {
    const result = await this.pool.query<ReviewRow>(
      `SELECT ${reviewSelect} FROM kol_claim_reviews WHERE review_id = $1`,
      [reviewId],
    );
    return result.rows[0] ? review(result.rows[0]) : null;
  }

  async appendReview(
    value: KolClaimReview,
    expectedPreviousReviewId: string | null,
  ): Promise<AppendClaimReviewResult> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      await client.query("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", [
        value.candidateId,
      ]);
      const currentCandidateResult = await client.query<CandidateRow>(
        `SELECT ${candidateSelect}
         FROM kol_claim_candidate_projection current
         WHERE current.candidate_id = $1
           AND ((current.deleted = FALSE AND current.available_at <= $2) OR (current.deleted = TRUE AND current.deleted_at <= $2))
           AND NOT EXISTS (
             SELECT 1 FROM kol_claim_candidate_projection child
             WHERE child.candidate_id = current.candidate_id
               AND child.previous_revision_id = current.revision_id
               AND ((child.deleted = FALSE AND child.available_at <= $2) OR (child.deleted = TRUE AND child.deleted_at <= $2))
           )
         LIMIT 2`,
        [value.candidateId, value.availableAt],
      );
      if (currentCandidateResult.rows.length !== 1)
        throw new Error("candidate current projection conflict");
      const currentCandidate = candidate(currentCandidateResult.rows[0] as CandidateRow);
      if (currentCandidate.deleted || currentCandidate.revisionId !== value.candidateRevisionId)
        throw new Error("candidate current projection conflict");

      const existingById = await client.query<ReviewRow>(
        `SELECT ${reviewSelect} FROM kol_claim_reviews WHERE review_id = $1 FOR UPDATE`,
        [value.reviewId],
      );
      if (existingById.rows[0]) {
        const existing = review(existingById.rows[0]);
        if (!sameReview(existing, value)) throw new Error("review identity conflict");
        await client.query("COMMIT");
        return { disposition: "EXISTING", review: existing };
      }

      const latest = await client.query<{ review_id: string }>(
        `SELECT current.review_id
         FROM kol_claim_reviews current
         WHERE current.candidate_id = $1 AND current.candidate_revision_id = $2
           AND NOT EXISTS (
             SELECT 1 FROM kol_claim_reviews child
             WHERE child.candidate_id = current.candidate_id
               AND child.candidate_revision_id = current.candidate_revision_id
               AND child.previous_review_id = current.review_id
           )
         LIMIT 1
         FOR UPDATE`,
        [value.candidateId, value.candidateRevisionId],
      );
      const actualPrevious = latest.rows[0]?.review_id ?? null;
      if (
        actualPrevious !== expectedPreviousReviewId ||
        value.previousReviewId !== expectedPreviousReviewId
      )
        throw new Error("review predecessor conflict");

      const inserted = await client.query<ReviewRow>(
        `INSERT INTO kol_claim_reviews
          (review_id, candidate_id, candidate_revision_id, decision, reason, comment, reviewer_ref,
           created_at, available_at, submission_fingerprint, previous_review_id)
         VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
         ON CONFLICT (review_id) DO NOTHING
         RETURNING ${reviewSelect}`,
        [
          value.reviewId,
          value.candidateId,
          value.candidateRevisionId,
          value.decision,
          value.reason,
          value.comment,
          value.reviewerRef,
          value.createdAt,
          value.availableAt,
          value.submissionFingerprint,
          expectedPreviousReviewId,
        ],
      );
      if (inserted.rows[0]) {
        await client.query("COMMIT");
        return { disposition: "INSERTED", review: review(inserted.rows[0]) };
      }
      const existingResult = await client.query<ReviewRow>(
        `SELECT ${reviewSelect} FROM kol_claim_reviews WHERE review_id = $1 FOR UPDATE`,
        [value.reviewId],
      );
      if (!existingResult.rows[0]) throw new Error("review conflict row disappeared");
      const existing = review(existingResult.rows[0]);
      if (!sameReview(existing, value)) throw new Error("review identity conflict");
      await client.query("COMMIT");
      return { disposition: "EXISTING", review: existing };
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }
}
