import { describe, expect, it } from "vitest";

import {
  computeCandidateIdFromPayload,
  computeCandidateRevisionIdFromPayload,
  computeClaimExtractionCandidatePayloadFingerprint,
  parseClaimExtractionCandidatePayload,
  type ClaimExtractionCandidatePayload,
} from "./claim-extraction.js";

const BASE_CANDIDATE = {
  schemaVersion: "claim-extraction-candidate-v1",
  candidateId: "1c266a9849669f02ba9b06c42377e8f517a62f7adf74ff7df31d4024b2e2602d",
  revisionId: "cc1b71cf97cd8ff1aa5160b3a2bb6adfdd9e6fdd95e4ef2c5a8ba0c08ec74b41",
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
      contentId: "fixture-content-1",
      contentVersion: "v1",
      contentRevisionId: "fixture-content-r1",
      contentAvailableTime: "2025-01-01T03:00:00Z",
      source: "fixture-source",
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
  modelProvider: "fixture",
  modelVersion: "v1",
  configurationFingerprint: "a".repeat(64),
  policyFingerprint: "b".repeat(64),
  recognitionRunId: "fixture-run-1",
  publishTime: "2025-01-01T00:00:00Z",
  ingestTime: "2025-01-01T01:00:00Z",
  processingTime: "2025-01-01T02:00:00Z",
  availableTime: "2025-01-01T03:00:00Z",
  reviewStatus: "UNREVIEWED",
  deleted: false,
  deletedAt: null,
  deletionReason: null,
} satisfies ClaimExtractionCandidatePayload;

function withRecomputedIds(
  candidate: ClaimExtractionCandidatePayload,
): ClaimExtractionCandidatePayload {
  const candidateId = computeCandidateIdFromPayload(candidate);
  const withCandidateId = { ...candidate, candidateId };
  return {
    ...withCandidateId,
    revisionId: computeCandidateRevisionIdFromPayload(withCandidateId),
  };
}

describe("Claim extraction candidate canonicalization", () => {
  it("treats equivalent RFC3339 offsets as the same stored payload", () => {
    const offsetCandidate = withRecomputedIds({
      ...BASE_CANDIDATE,
      anchors: [
        {
          ...BASE_CANDIDATE.anchors[0],
          contentAvailableTime: "2025-01-01T11:00:00+08:00",
        },
      ],
      publishTime: "2025-01-01T08:00:00+08:00",
      ingestTime: "2025-01-01T09:00:00+08:00",
      processingTime: "2025-01-01T10:00:00+08:00",
      availableTime: "2025-01-01T11:00:00+08:00",
    });

    expect(offsetCandidate.candidateId).toBe(BASE_CANDIDATE.candidateId);
    expect(offsetCandidate.revisionId).toBe(BASE_CANDIDATE.revisionId);
    expect(computeClaimExtractionCandidatePayloadFingerprint(offsetCandidate)).toBe(
      computeClaimExtractionCandidatePayloadFingerprint(BASE_CANDIDATE),
    );
    expect(parseClaimExtractionCandidatePayload(offsetCandidate)).toEqual(
      parseClaimExtractionCandidatePayload(BASE_CANDIDATE),
    );
  });

  it("rejects AMBIGUOUS statements attributed to SELF at runtime", () => {
    const invalid = withRecomputedIds({
      ...BASE_CANDIDATE,
      statementKind: "AMBIGUOUS",
      attribution: "SELF",
    });

    expect(() => parseClaimExtractionCandidatePayload(invalid)).toThrow(/AMBIGUOUS.*SELF/);
  });

  it("rejects rolling calendar dates instead of silently rewriting them", () => {
    const invalidInstant = withRecomputedIds({
      ...BASE_CANDIDATE,
      publishTime: "2025-02-30T00:00:00Z",
    });
    const invalidDate = withRecomputedIds({
      ...BASE_CANDIDATE,
      eventTimeStatus: "DATE_ONLY",
      eventDate: "2025-02-30",
    });

    expect(() => parseClaimExtractionCandidatePayload(invalidInstant)).toThrow(
      /publishTime.*valid timezone-aware RFC3339/,
    );
    expect(() => parseClaimExtractionCandidatePayload(invalidDate)).toThrow(
      /eventDate.*calendar date/,
    );
  });
});
