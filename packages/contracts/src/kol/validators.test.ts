import { describe, expect, it } from "vitest";

import {
  isKolClaimVisibleAt,
  validateKolClaimPayload,
  validateKolContentPayload,
  validateKolEvidencePayload,
  validateKolMentionPayload,
  validateKolPositionClaimPayload,
} from "./index";

const CONTENT = {
  schemaVersion: "kol-content-v1",
  contentId: "content-1",
  contentVersion: "content-version-1",
  revisionId: "content-revision-1",
  previousRevisionId: null,
  kolId: "kol-1",
  contentType: "POST",
  title: "A public statement",
  body: "A public statement about an instrument.",
  contentFingerprint: "8b48999f321c6ceef412f9d229ddef47f9b85a80e4a441059261a92802519964",
  contentFingerprintAlgorithmVersion: "sha256-kol-content-v1",
  eventTime: null,
  publishTime: "2026-08-24T08:00:00Z",
  ingestTime: "2026-08-24T08:01:00Z",
  processingTime: "2026-08-24T08:02:00Z",
  availableTime: "2026-08-24T08:03:00Z",
  source: "social-platform",
  sourceVersion: "platform-v1",
  deleted: false,
  deletedAt: null,
  deletionReason: null,
};

const EVIDENCE = {
  schemaVersion: "kol-evidence-v1",
  evidenceId: "evidence-1",
  revisionId: "evidence-revision-1",
  previousRevisionId: null,
  contentId: CONTENT.contentId,
  contentVersion: CONTENT.contentVersion,
  contentAvailableTime: CONTENT.availableTime,
  source: "social-platform",
  sourceVersion: "platform-v1",
  locatorType: "TEXT_RANGE",
  locator: "chars:0-18",
  excerpt: "A public statement",
  evidenceGrade: "PRIMARY_SOURCE",
  evidenceGradeVersion: "evidence-grade-v1",
  availableTime: "2026-08-24T08:04:00Z",
};

const CLAIM = {
  schemaVersion: "kol-claim-v1",
  claimId: "claim-1",
  revisionId: "claim-revision-1",
  previousRevisionId: null,
  contentId: CONTENT.contentId,
  contentVersion: CONTENT.contentVersion,
  contentAvailableTime: CONTENT.availableTime,
  kolId: CONTENT.kolId,
  statement: "This is a public statement.",
  statementKind: "DIRECT",
  instrumentId: "600519.SH",
  direction: "BULLISH",
  attribution: "SELF",
  uncertainty: "NONE",
  confidenceBps: 8000,
  reviewStatus: "UNREVIEWED",
  eventTime: "2026-08-24T07:59:00Z",
  publishTime: CONTENT.publishTime,
  ingestTime: CONTENT.ingestTime,
  processingTime: CONTENT.processingTime,
  availableTime: "2026-08-24T08:05:00Z",
  source: "claim-extractor",
  sourceVersion: "extractor-v1",
  evidence: [
    {
      evidenceId: EVIDENCE.evidenceId,
      evidenceRevisionId: EVIDENCE.revisionId,
      contentId: EVIDENCE.contentId,
      contentVersion: EVIDENCE.contentVersion,
      contentAvailableTime: EVIDENCE.contentAvailableTime,
      evidenceAvailableTime: EVIDENCE.availableTime,
      source: EVIDENCE.source,
      sourceVersion: EVIDENCE.sourceVersion,
    },
  ],
  deleted: false,
  deletedAt: null,
  deletionReason: null,
};

const POSITION_CLAIM = {
  schemaVersion: "kol-position-claim-v1",
  positionClaimId: "position-claim-1",
  revisionId: "position-claim-revision-1",
  previousRevisionId: null,
  claimId: CLAIM.claimId,
  claimRevisionId: CLAIM.revisionId,
  kolId: CLAIM.kolId,
  instrumentId: CLAIM.instrumentId,
  position: "LONG",
  timeHorizon: "SWING",
  executionSemantics: "NON_EXECUTABLE_POSITION_CLAIM",
  confidenceBps: 8000,
  reviewStatus: "UNREVIEWED",
  eventTime: CLAIM.eventTime,
  publishTime: CLAIM.publishTime,
  ingestTime: CLAIM.ingestTime,
  processingTime: CLAIM.processingTime,
  availableTime: "2026-08-24T08:05:00Z",
  source: "claim-extractor",
  sourceVersion: "extractor-v1",
  deleted: false,
  deletedAt: null,
  deletionReason: null,
};

describe("KOL runtime validators", () => {
  it("validate untrusted payloads through public runtime boundaries", () => {
    expect(validateKolContentPayload(CONTENT)).toEqual({ valid: true, errors: [] });
    expect(validateKolEvidencePayload(EVIDENCE)).toEqual({ valid: true, errors: [] });
    expect(validateKolClaimPayload(CLAIM)).toEqual({ valid: true, errors: [] });
    expect(validateKolPositionClaimPayload(POSITION_CLAIM)).toEqual({
      valid: true,
      errors: [],
    });
    expect(
      validateKolMentionPayload({
        schemaVersion: "kol-mention-v1",
        mentionId: "mention-1",
        revisionId: "mention-revision-1",
        previousRevisionId: null,
        contentId: CONTENT.contentId,
        contentVersion: CONTENT.contentVersion,
        kolId: CONTENT.kolId,
        mentionType: "INSTRUMENT",
        surfaceText: "600519",
        startOffset: 0,
        endOffset: 6,
        availableTime: CONTENT.availableTime,
        source: "mention-parser",
        sourceVersion: "parser-v1",
      }),
    ).toEqual({ valid: true, errors: [] });
  });

  it("rejects unknown fields, malformed time chains, evidence mismatch and bad confidence", () => {
    expect(validateKolClaimPayload({ ...CLAIM, unknown: true })).toMatchObject({ valid: false });
    expect(
      validateKolClaimPayload({ ...CLAIM, processingTime: "2026-08-24T08:00:30Z" }),
    ).toMatchObject({ valid: false });
    expect(
      validateKolClaimPayload({
        ...CLAIM,
        evidence: [{ ...CLAIM.evidence[0], contentVersion: "other-version" }],
      }),
    ).toMatchObject({ valid: false });
    expect(validateKolClaimPayload({ ...CLAIM, confidenceBps: 10001 })).toMatchObject({
      valid: false,
    });
    expect(validateKolClaimPayload({ ...CLAIM, instrumentId: "600519" })).toMatchObject({
      valid: false,
    });
  });

  it("keeps event time independent from publish order and marks paraphrase/ambiguity", () => {
    expect(
      validateKolClaimPayload({
        ...CLAIM,
        statementKind: "PARAPHRASE",
        uncertainty: "AMBIGUOUS",
        eventTime: "2026-08-20T08:00:00Z",
      }),
    ).toEqual({ valid: true, errors: [] });
  });

  it("does point-in-time visibility without allowing future payloads", () => {
    expect(isKolClaimVisibleAt(CLAIM, "2026-08-24T08:05:00Z")).toBe(true);
    expect(isKolClaimVisibleAt(CLAIM, "2026-08-24T08:04:59Z")).toBe(false);
    expect(isKolClaimVisibleAt({ ...CLAIM, availableTime: "2026-08-24T08:06:00Z" }, "2026-08-24T08:05:00Z")).toBe(false);
  });

  it("rejects self revisions and deletion inconsistencies while preserving non-execution semantics", () => {
    expect(
      validateKolContentPayload({ ...CONTENT, revisionId: "same", previousRevisionId: "same" }),
    ).toMatchObject({ valid: false });
    expect(
      validateKolContentPayload({
        ...CONTENT,
        deleted: true,
        deletedAt: null,
      }),
    ).toMatchObject({ valid: false });
    expect(
      validateKolPositionClaimPayload({
        ...POSITION_CLAIM,
        executionSemantics: "ORDER",
      }),
    ).toMatchObject({ valid: false });
    expect(
      validateKolPositionClaimPayload({ ...POSITION_CLAIM, orderId: "forbidden" }),
    ).toMatchObject({ valid: false });
  });
});
