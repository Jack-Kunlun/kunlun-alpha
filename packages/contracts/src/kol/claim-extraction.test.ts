import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

import {
  computeCandidateIdFromPayload,
  computeCandidateRevisionIdFromPayload,
  parseClaimExtractionCandidatePayload,
  validateClaimExtractionCandidatePayload,
  validateClaimReviewSubmissionPayload,
} from "./claim-extraction";

function candidate(overrides: Record<string, unknown> = {}): Record<string, unknown> {
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
    anchors: [
      {
        anchorType: "CONTENT",
        sourceIndex: 0,
        contentId: "content-1",
        contentVersion: "v1",
        contentRevisionId: "content-r1",
        contentAvailableTime: "2025-01-01T03:00:00Z",
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
    recognitionRunId: "run-1",
    publishTime: "2025-01-01T00:00:00Z",
    ingestTime: "2025-01-01T01:00:00Z",
    processingTime: "2025-01-01T02:00:00Z",
    availableTime: "2025-01-01T03:00:00Z",
    reviewStatus: "UNREVIEWED",
    deleted: false,
    deletedAt: null,
    deletionReason: null,
    ...overrides,
  };
  const candidateId = overrides.candidateId ?? computeCandidateIdFromPayload(payload);
  const withCandidateId = { ...payload, candidateId };
  return {
    ...withCandidateId,
    revisionId: overrides.revisionId ?? computeCandidateRevisionIdFromPayload(withCandidateId),
  };
}

describe("claim extraction contracts", () => {
  it("exposes a closed candidate runtime boundary", () => {
    expect(() => parseClaimExtractionCandidatePayload({})).toThrow();
  });

  it("rejects client-owned review provenance", () => {
    expect(
      validateClaimReviewSubmissionPayload({
        schemaVersion: "claim-review-submission-v1",
        clientRequestId: "request-1",
        candidateId: "candidate-1",
        candidateRevisionId: "revision-1",
        decision: "APPROVED",
        reviewerRef: "forged",
      }),
    ).toMatchObject({ valid: false });
  });

  it("uses the shared canonical instrument mapping and actual instant ordering", () => {
    expect(validateClaimExtractionCandidatePayload(candidate()).valid).toBe(true);
    expect(
      validateClaimExtractionCandidatePayload(candidate({ instrumentId: "600519.SZ" })).valid,
    ).toBe(false);
    expect(
      validateClaimExtractionCandidatePayload(candidate({ instrumentId: "000001.SH" })).valid,
    ).toBe(false);
    expect(
      validateClaimExtractionCandidatePayload(
        candidate({
          publishTime: "2025-01-01T08:00:00+08:00",
          ingestTime: "2025-01-01T00:30:00Z",
          processingTime: "2025-01-01T01:00:00Z",
          availableTime: "2025-01-01T03:00:00Z",
        }),
      ).valid,
    ).toBe(true);
  });

  it("enforces event-time, attribution, and anchor provenance invariants", () => {
    const baseAnchor = (candidate().anchors as Array<Record<string, unknown>>)[0];
    expect(
      validateClaimExtractionCandidatePayload(
        candidate({
          eventTimeStatus: "EXACT",
          eventTime: "2025-01-02T08:00:00+08:00",
        }),
      ).valid,
    ).toBe(true);
    expect(
      validateClaimExtractionCandidatePayload(
        candidate({
          eventTimeStatus: "EXACT",
          eventTime: "2025-01-02T08:00:00+08:00",
          eventDate: "2025-01-02",
        }),
      ).valid,
    ).toBe(false);
    expect(
      validateClaimExtractionCandidatePayload(
        candidate({
          statementKind: "QUOTE",
          attribution: "SELF",
        }),
      ).valid,
    ).toBe(false);
    expect(
      validateClaimExtractionCandidatePayload(
        candidate({
          anchors: [{ ...baseAnchor, mediaId: "media-1" }],
        }),
      ).valid,
    ).toBe(false);
    expect(
      validateClaimExtractionCandidatePayload(
        candidate({
          anchors: [{ ...baseAnchor, contentAvailableTime: "2025-01-01T04:00:00Z" }],
        }),
      ).valid,
    ).toBe(false);
  });

  it("rejects strict bps booleans and unknown candidate fields", () => {
    expect(validateClaimExtractionCandidatePayload(candidate({ confidenceBps: true })).valid).toBe(
      false,
    );
    expect(validateClaimExtractionCandidatePayload(candidate({ unexpected: "field" })).valid).toBe(
      false,
    );
    expect(() =>
      parseClaimExtractionCandidatePayload(candidate({ confidenceBps: true })),
    ).toThrow();
  });

  it("keeps paraphrase attribution and tombstone timing closed", () => {
    expect(
      validateClaimExtractionCandidatePayload(
        candidate({
          statementKind: "PARAPHRASE",
          attribution: "UNKNOWN",
        }),
      ).valid,
    ).toBe(false);
    expect(
      validateClaimExtractionCandidatePayload(
        candidate({
          deleted: true,
          deletedAt: "2025-01-01T02:00:00Z",
          deletionReason: "撤回",
        }),
      ).valid,
    ).toBe(false);
  });

  it("publishes the ambiguous-self attribution rule in JSON Schema", () => {
    const schema = JSON.parse(
      readFileSync("schemas/kol/claim-extraction-candidate.json", "utf8"),
    ) as {
      allOf?: Array<Record<string, unknown>>;
    };
    const rule = schema.allOf?.find((item) => {
      const properties = (item.if as Record<string, unknown> | undefined)?.properties as
        Record<string, unknown> | undefined;
      return (
        (properties?.statementKind as Record<string, unknown> | undefined)?.const === "AMBIGUOUS"
      );
    });
    expect(rule).toEqual(
      expect.objectContaining({
        then: expect.objectContaining({
          properties: expect.objectContaining({
            attribution: expect.objectContaining({ not: { const: "SELF" } }),
          }),
        }),
      }),
    );
  });

  it("matches the fixed cross-language candidate identity fixtures", () => {
    const fixtures = JSON.parse(
      readFileSync("src/kol/claim-extraction-identity-fixtures.json", "utf8"),
    ) as {
      cases: Array<{
        payload: Record<string, unknown>;
        expectedCandidateId: string;
        expectedRevisionId: string;
      }>;
    };
    for (const item of fixtures.cases) {
      expect(computeCandidateIdFromPayload(item.payload)).toBe(item.expectedCandidateId);
      expect(computeCandidateRevisionIdFromPayload(item.payload)).toBe(item.expectedRevisionId);
    }
  });
});
