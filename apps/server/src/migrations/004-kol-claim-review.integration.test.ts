import { randomUUID } from "node:crypto";
import { createHash } from "node:crypto";
import { Pool } from "pg";
import { describe, expect, it } from "vitest";
import {
  computeCandidateIdFromPayload,
  computeCandidateRevisionIdFromPayload,
  computeClaimExtractionCandidatePayloadFingerprint,
  parseClaimExtractionCandidatePayload,
} from "@kunlun/contracts/kol";
import { MigrationRunner, PostgresSqlDriver } from "@kunlun/db";
import { migrations } from "./index";
import { PostgresClaimReviewRepository } from "../modules/claim-review/postgres-claim-review.repository";
import { InMemoryClaimReviewRepository } from "../modules/claim-review/in-memory-claim-review.repository";
import type { ClaimCandidateProjection } from "../modules/claim-review/claim-review-repository";
import type { KolClaimReview } from "@kunlun/shared-types";

const dsn = process.env.KUNLUN_TEST_POSTGRES_DSN;
const run = dsn ? describe : describe.skip;

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

function projectionFromPayload(payload: Record<string, unknown>): ClaimCandidateProjection {
  const canonicalPayload = parseClaimExtractionCandidatePayload(payload) as Record<string, unknown>;
  const payloadFingerprint = computeClaimExtractionCandidatePayloadFingerprint(canonicalPayload);
  return {
    candidateId: canonicalPayload.candidateId as string,
    revisionId: canonicalPayload.revisionId as string,
    previousRevisionId: canonicalPayload.previousRevisionId as string | null,
    availableAt: canonicalPayload.availableTime as string,
    deleted: canonicalPayload.deleted === true,
    deletedAt: canonicalPayload.deletedAt as string | null,
    deletionReason: canonicalPayload.deletionReason as string | null,
    confidenceBps: canonicalPayload.confidenceBps as number,
    integrityFingerprint: fingerprint({
      algorithmVersion: canonicalPayload.algorithmVersion,
      payloadFingerprint,
    }),
    payloadFingerprint,
    canonicalPayload,
  };
}

function candidate(
  seed: string,
  availableTime = "2025-01-01T00:00:00.000Z",
): ClaimCandidateProjection {
  const payload: Record<string, unknown> = {
    schemaVersion: "claim-extraction-candidate-v1",
    candidateId: "pending-candidate",
    revisionId: "pending-revision",
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
    anchors: [
      {
        anchorType: "CONTENT",
        sourceIndex: 0,
        contentId: `content-${seed}`,
        contentVersion: "v1",
        contentRevisionId: `content-${seed}-r1`,
        contentAvailableTime: availableTime,
        source: "test",
        sourceVersion: "v1",
        startOffset: 0,
        endOffset: 4,
        excerpt: "公开表述",
        evidenceGrade: "PRIMARY_SOURCE",
        evidenceGradeVersion: "evidence-grade-v1",
      },
    ],
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
    recognitionRunId: `run-${seed}`,
    publishTime: availableTime,
    ingestTime: availableTime,
    processingTime: availableTime,
    availableTime,
    reviewStatus: "UNREVIEWED",
    deleted: false,
    deletedAt: null,
    deletionReason: null,
  };
  const candidateId = computeCandidateIdFromPayload(payload);
  const withCandidateId = { ...payload, candidateId };
  const canonicalPayload: Record<string, unknown> = {
    ...withCandidateId,
    revisionId: computeCandidateRevisionIdFromPayload(withCandidateId),
  };
  return projectionFromPayload(canonicalPayload);
}

function successor(
  predecessor: ClaimCandidateProjection,
  availableTime: string,
  suffix: string,
): ClaimCandidateProjection {
  const payload: Record<string, unknown> = {
    ...predecessor.canonicalPayload,
    revisionId: "pending-revision",
    previousRevisionId: predecessor.revisionId,
    processingTime: availableTime,
    availableTime,
    recognitionRunId: `run-${suffix}`,
  };
  payload.revisionId = computeCandidateRevisionIdFromPayload(payload);
  return projectionFromPayload(payload);
}

function tombstone(
  predecessor: ClaimCandidateProjection,
  availableTime: string,
  deletedAt: string,
): ClaimCandidateProjection {
  const payload: Record<string, unknown> = {
    ...predecessor.canonicalPayload,
    revisionId: "pending-revision",
    previousRevisionId: predecessor.revisionId,
    processingTime: availableTime,
    availableTime,
    recognitionRunId: "run-tombstone",
    deleted: true,
    deletedAt,
    deletionReason: "source_deleted",
  };
  payload.revisionId = computeCandidateRevisionIdFromPayload(payload);
  return projectionFromPayload(payload);
}

function review(
  reviewId: string,
  candidate: ClaimCandidateProjection,
  previousReviewId: string | null,
  fingerprint: string,
): KolClaimReview {
  return {
    schemaVersion: "claim-review-v1",
    reviewId,
    candidateId: candidate.candidateId,
    candidateRevisionId: candidate.revisionId,
    decision: "APPROVED",
    reason: "审核公开措辞",
    comment: null,
    reviewerRef: "trusted-reviewer",
    createdAt: "2025-01-01T01:00:00.000Z",
    availableAt: "2025-01-01T01:00:00.000Z",
    submissionFingerprint: fingerprint,
    previousReviewId,
    reviewMeaning: "PUBLIC_WORDING_REVIEWED_NOT_FACT_OR_EXECUTION",
  };
}

run("KOL claim review PostgreSQL integration", () => {
  it("enforces append-only heads, concurrent idempotency, rollback, and restart reads", async () => {
    const context = await openSchema();
    try {
      const runner = new MigrationRunner(context.driver);
      expect(await runner.migrate(migrations)).toBeGreaterThan(0);
      expect(await runner.migrate(migrations)).toBe(0);
      const repository = new PostgresClaimReviewRepository(context.pool);
      const candidateOne = candidate("one");
      const candidateTwo = candidate("two");
      const candidateThree = candidate("three");
      await repository.storeCandidateProjection(candidateOne);
      await repository.storeCandidateProjection(candidateTwo);
      await repository.storeCandidateProjection(candidateThree);

      const root = review("review-root", candidateOne, null, "1".repeat(64));
      const concurrent = await Promise.all([
        repository.appendReview(root, null),
        repository.appendReview(root, null),
      ]);
      expect(concurrent.map((item) => item.disposition).sort()).toEqual(["EXISTING", "INSERTED"]);
      await expect(
        repository.appendReview(
          { ...root, reason: "篡改", submissionFingerprint: "2".repeat(64) },
          null,
        ),
      ).rejects.toThrow(/conflict/i);

      const successor = review("review-successor", candidateOne, root.reviewId, "3".repeat(64));
      expect((await repository.appendReview(successor, root.reviewId)).disposition).toBe(
        "INSERTED",
      );
      expect(
        (
          await new PostgresClaimReviewRepository(context.pool).latestReview(
            candidateOne.candidateId,
            candidateOne.revisionId,
          )
        )?.reviewId,
      ).toBe(successor.reviewId);

      await expect(
        context.pool.query(
          `INSERT INTO kol_claim_reviews (review_id, candidate_id, candidate_revision_id, decision, reason, reviewer_ref, created_at, available_at, submission_fingerprint, previous_review_id)
         VALUES ('cross-review',$1,$2,'APPROVED','跨候选','trusted-reviewer','2025-01-01T01:00:00Z','2025-01-01T01:00:00Z',$3,'review-root')`,
          [candidateTwo.candidateId, candidateTwo.revisionId, "4".repeat(64)],
        ),
      ).rejects.toThrow();

      await context.pool.query(
        `INSERT INTO kol_claim_reviews (review_id, candidate_id, candidate_revision_id, decision, reason, reviewer_ref, created_at, available_at, submission_fingerprint, previous_review_id)
         VALUES ('candidate-3-root',$1,$2,'APPROVED','根','trusted-reviewer','2025-01-01T01:00:00Z','2025-01-01T01:00:00Z',$3,NULL)`,
        [candidateThree.candidateId, candidateThree.revisionId, "5".repeat(64)],
      );
      await expect(
        context.pool.query(
          `INSERT INTO kol_claim_reviews (review_id, candidate_id, candidate_revision_id, decision, reason, reviewer_ref, created_at, available_at, submission_fingerprint, previous_review_id)
         VALUES ('candidate-3-fork-a',$1,$2,'APPROVED','分支','trusted-reviewer','2025-01-01T01:00:00Z','2025-01-01T01:00:00Z',$3,'candidate-3-root')`,
          [candidateThree.candidateId, candidateThree.revisionId, "6".repeat(64)],
        ),
      ).resolves.toBeDefined();
      await expect(
        context.pool.query(
          `INSERT INTO kol_claim_reviews (review_id, candidate_id, candidate_revision_id, decision, reason, reviewer_ref, created_at, available_at, submission_fingerprint, previous_review_id)
         VALUES ('candidate-3-fork-b',$1,$2,'APPROVED','分支','trusted-reviewer','2025-01-01T01:00:00Z','2025-01-01T01:00:00Z',$3,'candidate-3-root')`,
          [candidateThree.candidateId, candidateThree.revisionId, "7".repeat(64)],
        ),
      ).rejects.toThrow();

      const client = await context.pool.connect();
      try {
        await client.query("BEGIN");
        await client.query(
          "INSERT INTO kol_claim_reviews (review_id, candidate_id, candidate_revision_id, decision, reason, reviewer_ref, created_at, available_at, submission_fingerprint) VALUES ('rollback-review',$1,$2,'APPROVED','回滚','trusted-reviewer','2025-01-01T01:00:00Z','2025-01-01T01:00:00Z',$3)",
          [candidateTwo.candidateId, candidateTwo.revisionId, "8".repeat(64)],
        );
        await client.query("ROLLBACK");
      } finally {
        client.release();
      }
      const rollbackCheck = await context.pool.query(
        "SELECT review_id FROM kol_claim_reviews WHERE review_id = 'rollback-review'",
      );
      expect(rollbackCheck.rows).toHaveLength(0);
    } finally {
      await context.pool.end();
      await context.driver.close();
      await dropSchema(context.schema);
    }
  });

  it("enforces candidate available-time FK/CHECKs, concurrent fork CAS, and rollback", async () => {
    const context = await openSchema();
    try {
      const runner = new MigrationRunner(context.driver);
      await runner.migrate(migrations);
      const repository = new PostgresClaimReviewRepository(context.pool);
      const root = candidate("available-time");
      await repository.storeCandidateProjection(root);
      const validChild = successor(root, "2025-01-02T01:00:00.000Z", "valid-child");
      await repository.storeCandidateProjection(validChild);
      expect(
        (await repository.findCandidate(root.candidateId, validChild.revisionId))?.revisionId,
      ).toBe(validChild.revisionId);
      await context.pool.query(
        "UPDATE kol_claim_candidate_projection SET canonical_payload = jsonb_set(canonical_payload, '{statement}', to_jsonb($1::text)) WHERE candidate_id = $2 AND revision_id = $3",
        ["篡改", root.candidateId, root.revisionId],
      );
      await expect(repository.findCandidate(root.candidateId, root.revisionId)).rejects.toThrow(
        /integrity|identity/i,
      );

      const forged = successor(validChild, "2025-01-03T01:00:00.000Z", "forged");
      await expect(
        context.pool.query(
          `INSERT INTO kol_claim_candidate_projection
          (candidate_id, revision_id, previous_revision_id, previous_available_at, available_at, deleted, deleted_at, deletion_reason, confidence_bps, integrity_fingerprint, payload_fingerprint, canonical_payload)
         VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)`,
          [
            forged.candidateId,
            forged.revisionId,
            forged.previousRevisionId,
            "2025-01-01T00:00:01Z",
            forged.availableAt,
            forged.deleted,
            forged.deletedAt,
            forged.deletionReason,
            forged.confidenceBps,
            forged.integrityFingerprint,
            forged.payloadFingerprint,
            forged.canonicalPayload,
          ],
        ),
      ).rejects.toThrow();

      const equalTime = successor(validChild, "2025-01-02T01:00:00.000Z", "equal-time");
      await expect(
        context.pool.query(
          `INSERT INTO kol_claim_candidate_projection
          (candidate_id, revision_id, previous_revision_id, previous_available_at, available_at, deleted, deleted_at, deletion_reason, confidence_bps, integrity_fingerprint, payload_fingerprint, canonical_payload)
         VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)`,
          [
            equalTime.candidateId,
            equalTime.revisionId,
            equalTime.previousRevisionId,
            validChild.availableAt,
            equalTime.availableAt,
            equalTime.deleted,
            equalTime.deletedAt,
            equalTime.deletionReason,
            equalTime.confidenceBps,
            equalTime.integrityFingerprint,
            equalTime.payloadFingerprint,
            equalTime.canonicalPayload,
          ],
        ),
      ).rejects.toThrow();

      const reversedTime = successor(validChild, "2025-01-01T01:00:00.000Z", "reversed-time");
      await expect(
        context.pool.query(
          `INSERT INTO kol_claim_candidate_projection
          (candidate_id, revision_id, previous_revision_id, previous_available_at, available_at, deleted, deleted_at, deletion_reason, confidence_bps, integrity_fingerprint, payload_fingerprint, canonical_payload)
         VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)`,
          [
            reversedTime.candidateId,
            reversedTime.revisionId,
            reversedTime.previousRevisionId,
            validChild.availableAt,
            reversedTime.availableAt,
            reversedTime.deleted,
            reversedTime.deletedAt,
            reversedTime.deletionReason,
            reversedTime.confidenceBps,
            reversedTime.integrityFingerprint,
            reversedTime.payloadFingerprint,
            reversedTime.canonicalPayload,
          ],
        ),
      ).rejects.toThrow();

      const forkRoot = candidate("concurrent-fork");
      await repository.storeCandidateProjection(forkRoot);
      const forkA = successor(forkRoot, "2025-01-02T01:00:00.000Z", "fork-a");
      const forkB = successor(forkRoot, "2025-01-03T01:00:00.000Z", "fork-b");
      const forkResults = await Promise.allSettled([
        repository.storeCandidateProjection(forkA),
        repository.storeCandidateProjection(forkB),
      ]);
      expect(forkResults.filter((item) => item.status === "fulfilled")).toHaveLength(1);
      expect(forkResults.filter((item) => item.status === "rejected")).toHaveLength(1);

      expect(await runner.rollback(migrations, 3)).toBeGreaterThan(0);
      expect(await context.driver.hasTable("kol_claim_candidate_projection")).toBe(false);
    } finally {
      await context.pool.end();
      await context.driver.close();
      await dropSchema(context.schema);
    }
  });

  it("preserves canonical replay, microseconds, tombstone PIT, and repository parity", async () => {
    const context = await openSchema();
    try {
      const runner = new MigrationRunner(context.driver);
      await runner.migrate(migrations);
      const postgres = new PostgresClaimReviewRepository(context.pool);
      const memory = new InMemoryClaimReviewRepository();

      const root = candidate("offset-replay");
      const rootPayload = root.canonicalPayload as Record<string, unknown>;
      const rootAnchors = rootPayload.anchors as Array<Record<string, unknown>>;
      const offsetReplay = projectionFromPayload({
        ...rootPayload,
        anchors: [{ ...rootAnchors[0], contentAvailableTime: "2025-01-01T08:00:00+08:00" }],
        publishTime: "2025-01-01T08:00:00+08:00",
        ingestTime: "2025-01-01T08:00:00+08:00",
        processingTime: "2025-01-01T08:00:00+08:00",
        availableTime: "2025-01-01T08:00:00+08:00",
      });
      await postgres.storeCandidateProjection(root);
      await memory.storeCandidateProjection(root);
      await expect(postgres.storeCandidateProjection(offsetReplay)).resolves.toBeUndefined();
      await expect(memory.storeCandidateProjection(offsetReplay)).resolves.toBeUndefined();

      const microRoot = candidate("microseconds", "2025-01-02T00:00:00.123456Z");
      const microChild = successor(microRoot, "2025-01-02T00:00:00.123457Z", "micro-child");
      await postgres.storeCandidateProjection(microRoot);
      await memory.storeCandidateProjection(microRoot);
      await postgres.storeCandidateProjection(microChild);
      await memory.storeCandidateProjection(microChild);
      expect(
        (await postgres.findCandidate(microRoot.candidateId, microChild.revisionId))?.availableAt,
      ).toBe("2025-01-02T00:00:00.123457Z");
      expect(
        (await memory.findCandidate(microRoot.candidateId, microChild.revisionId))?.availableAt,
      ).toBe("2025-01-02T00:00:00.123457Z");

      const tombstoneRoot = candidate("tombstone");
      const deleted = tombstone(tombstoneRoot, "2025-01-02T00:00:00Z", "2025-01-03T00:00:00Z");
      await postgres.storeCandidateProjection(tombstoneRoot);
      await memory.storeCandidateProjection(tombstoneRoot);
      await postgres.storeCandidateProjection(deleted);
      await memory.storeCandidateProjection(deleted);
      expect(
        (await postgres.latestCandidate(tombstoneRoot.candidateId, "2025-01-02T12:00:00Z"))
          ?.revisionId,
      ).toBe(tombstoneRoot.revisionId);
      expect(
        (await memory.latestCandidate(tombstoneRoot.candidateId, "2025-01-02T12:00:00Z"))
          ?.revisionId,
      ).toBe(tombstoneRoot.revisionId);
      await expect(
        postgres.latestCandidate(tombstoneRoot.candidateId, "2025-01-03T00:00:00Z"),
      ).resolves.toBeNull();
      await expect(
        memory.latestCandidate(tombstoneRoot.candidateId, "2025-01-03T00:00:00Z"),
      ).resolves.toBeNull();
      await expect(
        memory.storeCandidateProjection({ ...root, payloadFingerprint: "0".repeat(64) }),
      ).rejects.toThrow(/fingerprint conflict/i);

      const raceRoot = candidate("review-race");
      const raceChild = successor(raceRoot, "2025-01-01T00:30:00Z", "review-race-child");
      const staleReview = review("review-race-stale", raceRoot, null, "9".repeat(64));
      await postgres.storeCandidateProjection(raceRoot);
      await memory.storeCandidateProjection(raceRoot);
      const raceClient = await context.pool.connect();
      try {
        await raceClient.query("BEGIN");
        await raceClient.query("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", [
          raceRoot.candidateId,
        ]);
        await raceClient.query(
          `INSERT INTO kol_claim_candidate_projection
            (candidate_id, revision_id, previous_revision_id, previous_available_at, available_at, deleted, deleted_at,
             deletion_reason, confidence_bps, integrity_fingerprint, payload_fingerprint, canonical_payload)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)`,
          [
            raceChild.candidateId,
            raceChild.revisionId,
            raceChild.previousRevisionId,
            raceRoot.availableAt,
            raceChild.availableAt,
            raceChild.deleted,
            raceChild.deletedAt,
            raceChild.deletionReason,
            raceChild.confidenceBps,
            raceChild.integrityFingerprint,
            raceChild.payloadFingerprint,
            raceChild.canonicalPayload,
          ],
        );
        const pendingReview = postgres.appendReview(staleReview, null);
        await raceClient.query("COMMIT");
        await expect(pendingReview).rejects.toThrow(/candidate current projection conflict/i);
      } finally {
        raceClient.release();
      }
      await memory.storeCandidateProjection(raceChild);
      await expect(memory.appendReview(staleReview, null)).rejects.toThrow(
        /candidate current projection conflict/i,
      );
    } finally {
      await context.pool.end();
      await context.driver.close();
      await dropSchema(context.schema);
    }
  });
});

async function openSchema(): Promise<{ driver: PostgresSqlDriver; pool: Pool; schema: string }> {
  if (!dsn) throw new Error("KUNLUN_TEST_POSTGRES_DSN is required");
  const schema = `test_${randomUUID().replaceAll("-", "")}`;
  const admin = new Pool({ connectionString: dsn });
  try {
    await admin.query(`CREATE SCHEMA "${schema}"`);
  } finally {
    await admin.end();
  }
  const pool = new Pool({ connectionString: dsn, options: `-c search_path="${schema}"` });
  const driver = new PostgresSqlDriver({
    connectionString: dsn,
    options: `-c search_path="${schema}"`,
  });
  return { driver, pool, schema };
}

async function dropSchema(schema: string): Promise<void> {
  if (!dsn) return;
  const admin = new Pool({ connectionString: dsn });
  try {
    await admin.query(`DROP SCHEMA "${schema}" CASCADE`);
  } finally {
    await admin.end();
  }
}
