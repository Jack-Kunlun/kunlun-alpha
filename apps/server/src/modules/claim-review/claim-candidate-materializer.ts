import { Inject, Injectable } from "@nestjs/common";
import { createHash } from "node:crypto";
import {
  computeCandidateIdFromPayload,
  computeCandidateRevisionIdFromPayload,
  computeClaimExtractionCandidatePayloadFingerprint,
  parseClaimExtractionCandidatePayload,
} from "@kunlun/contracts/kol";
import type {
  ClaimCandidateProjection,
  ClaimCandidateProjectionStore,
} from "./claim-review-repository";
import { CLAIM_CANDIDATE_PROJECTION_STORE } from "./claim-review.tokens";

type JsonObject = Record<string, unknown>;

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === "object") {
    const record = value as JsonObject;
    return Object.fromEntries(
      Object.keys(record)
        .sort()
        .map((key) => [key, canonical(record[key])]),
    );
  }
  return value;
}

function canonicalObject(value: unknown): Readonly<Record<string, unknown>> {
  if (value === null || typeof value !== "object" || Array.isArray(value))
    throw new Error("candidate payload must be an object");
  return canonical(value) as Readonly<Record<string, unknown>>;
}

function fingerprint(value: unknown): string {
  return createHash("sha256")
    .update(JSON.stringify(canonical(value)), "utf8")
    .digest("hex");
}

function text(value: unknown, name: string): string {
  if (typeof value !== "string" || value.length === 0) throw new Error(`${name} is invalid`);
  return value;
}

function nullableText(value: unknown, name: string): string | null {
  if (value === null) return null;
  return text(value, name);
}

@Injectable()
export class ClaimCandidateMaterializer {
  constructor(
    @Inject(CLAIM_CANDIDATE_PROJECTION_STORE)
    private readonly store: ClaimCandidateProjectionStore,
  ) {}

  async materialize(value: unknown): Promise<ClaimCandidateProjection> {
    const payload = parseClaimExtractionCandidatePayload(value) as JsonObject;
    if (computeCandidateIdFromPayload(payload) !== payload.candidateId)
      throw new Error("candidateId integrity conflict");
    if (computeCandidateRevisionIdFromPayload(payload) !== payload.revisionId)
      throw new Error("revisionId integrity conflict");
    const canonicalPayload = canonicalObject(payload);
    const payloadFingerprint = computeClaimExtractionCandidatePayloadFingerprint(canonicalPayload);
    const projection: ClaimCandidateProjection = {
      candidateId: text(payload.candidateId, "candidateId"),
      revisionId: text(payload.revisionId, "revisionId"),
      previousRevisionId: nullableText(payload.previousRevisionId, "previousRevisionId"),
      availableAt: text(payload.availableTime, "availableTime"),
      deleted: payload.deleted === true,
      deletedAt: nullableText(payload.deletedAt, "deletedAt"),
      deletionReason: nullableText(payload.deletionReason, "deletionReason"),
      confidenceBps: typeof payload.confidenceBps === "number" ? payload.confidenceBps : -1,
      integrityFingerprint: fingerprint({
        algorithmVersion: payload.algorithmVersion,
        payloadFingerprint,
      }),
      payloadFingerprint,
      canonicalPayload,
    };
    await this.store.storeCandidateProjection(projection);
    return projection;
  }
}

export { computeClaimExtractionCandidatePayloadFingerprint as claimCandidatePayloadFingerprint };
