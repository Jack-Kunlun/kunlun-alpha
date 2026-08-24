import { describe, expect, it } from "vitest";

import {
  APPROVED_REVIEW_SEMANTICS,
  parseKolDomainSnapshotPayload,
  selectKolDomainSnapshotAt,
  computeKolContentFingerprint,
  validateKolClaimPayload,
  validateKolContentPayload,
  validateKolEvidencePayload,
  validateKolPositionClaimPayload,
} from "./index";

function fingerprint(title: string, body: string): string {
  return computeKolContentFingerprint(title, body);
}

const CONTENT = {
  schemaVersion: "kol-content-v1",
  contentId: "content-aggregate-1",
  contentVersion: "content-version-1",
  revisionId: "content-revision-1",
  previousRevisionId: null,
  kolId: "kol-1",
  contentType: "POST",
  title: "A public statement",
  body: "A public statement about an instrument.",
  contentFingerprint: fingerprint("A public statement", "A public statement about an instrument."),
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
  evidenceId: "evidence-aggregate-1",
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
  claimId: "claim-aggregate-1",
  revisionId: "claim-revision-1",
  previousRevisionId: null,
  contentId: CONTENT.contentId,
  contentVersion: CONTENT.contentVersion,
  contentAvailableTime: CONTENT.availableTime,
  kolId: CONTENT.kolId,
  statement: "This is a public statement.",
  statementKind: "QUOTE",
  instrumentId: "600519.SH",
  direction: "BULLISH",
  attribution: "QUOTED",
  uncertainty: "AMBIGUOUS",
  confidenceBps: 8000,
  reviewStatus: "APPROVED",
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
  positionClaimId: "position-aggregate-1",
  revisionId: "position-revision-1",
  previousRevisionId: null,
  claimId: CLAIM.claimId,
  claimRevisionId: CLAIM.revisionId,
  kolId: CLAIM.kolId,
  instrumentId: CLAIM.instrumentId,
  position: "LONG",
  timeHorizon: "SWING",
  executionSemantics: "NON_EXECUTABLE_POSITION_CLAIM",
  confidenceBps: 8000,
  reviewStatus: "APPROVED",
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

describe("P4-N06 repair regressions", () => {
  it("keeps APPROVED as a wording-review label only", () => {
    expect(APPROVED_REVIEW_SEMANTICS).toBe("PUBLIC_WORDING_REVIEWED_NOT_FACT_OR_EXECUTION");
  });

  it("requires a versioned evidence grade and validates the content fingerprint", () => {
    expect(validateKolEvidencePayload(EVIDENCE)).toEqual({ valid: true, errors: [] });
    expect(validateKolEvidencePayload({ ...EVIDENCE, evidenceGrade: "UNKNOWN" })).toMatchObject({
      valid: false,
    });
    expect(
      validateKolContentPayload({ ...CONTENT, body: "tampered body" }),
    ).toMatchObject({ valid: false });
  });

  it("rejects exchange-prefix mismatches and overlong fields", () => {
    expect(validateKolClaimPayload({ ...CLAIM, instrumentId: "600519.SZ" })).toMatchObject({
      valid: false,
    });
    expect(validateKolPositionClaimPayload({ ...POSITION_CLAIM, instrumentId: "000001.SH" })).toMatchObject({
      valid: false,
    });
    expect(validateKolClaimPayload({ ...CLAIM, statement: "x".repeat(10001) })).toMatchObject({
      valid: false,
    });
    expect(validateKolEvidencePayload({ ...EVIDENCE, excerpt: "x".repeat(4001) })).toMatchObject({
      valid: false,
    });
    expect(validateKolEvidencePayload({ ...EVIDENCE, locator: "x".repeat(2049) })).toMatchObject({
      valid: false,
    });
  });

  it("locks the quote/reported/ambiguous combination matrix", () => {
    expect(validateKolClaimPayload({ ...CLAIM, statementKind: "QUOTE", attribution: "SELF" })).toMatchObject({
      valid: false,
    });
    expect(validateKolClaimPayload({ ...CLAIM, statementKind: "PARAPHRASE", attribution: "REPORTED" })).toEqual({
      valid: true,
      errors: [],
    });
    expect(validateKolClaimPayload({ ...CLAIM, statementKind: "AMBIGUOUS", uncertainty: "NONE" })).toMatchObject({
      valid: false,
    });
  });

  it("validates aggregate links and selects the latest visible revision without future leakage", () => {
    const futureContent = {
      ...CONTENT,
      contentVersion: "content-version-2",
      revisionId: "content-revision-2",
      previousRevisionId: CONTENT.revisionId,
      body: "A corrected public statement about an instrument.",
      contentFingerprint: fingerprint("A public statement", "A corrected public statement about an instrument."),
      availableTime: "2026-08-24T08:10:00Z",
    };
    const snapshot = parseKolDomainSnapshotPayload({
      content: [CONTENT, futureContent],
      evidence: [EVIDENCE],
      claims: [CLAIM],
      positionClaims: [POSITION_CLAIM],
    });
    expect(selectKolDomainSnapshotAt(snapshot, "2026-08-24T08:05:00Z").content[0]).toEqual(CONTENT);
    expect(selectKolDomainSnapshotAt(snapshot, "2026-08-24T08:10:00Z").content[0]).toEqual(futureContent);
    expect(() =>
      parseKolDomainSnapshotPayload({
        content: [CONTENT],
        evidence: [{ ...EVIDENCE, contentVersion: "missing" }],
        claims: [CLAIM],
        positionClaims: [POSITION_CLAIM],
      }),
    ).toThrow(/content/);
    expect(() =>
      parseKolDomainSnapshotPayload({
        content: [CONTENT, { ...futureContent, previousRevisionId: null }],
        evidence: [EVIDENCE],
        claims: [CLAIM],
        positionClaims: [POSITION_CLAIM],
      }),
    ).toThrow(/root|fork/);
  });

  it("groups revision graphs by logical id and accepts child-before-parent input", () => {
    const child = {
      ...CONTENT,
      contentVersion: "content-version-2",
      revisionId: "content-revision-2",
      previousRevisionId: CONTENT.revisionId,
      availableTime: "2026-08-24T08:04:00Z",
    };
    const other = {
      ...CONTENT,
      contentId: "content-aggregate-2",
      contentVersion: "other-version-1",
      revisionId: "other-revision-1",
      availableTime: "2026-08-24T08:03:00Z",
    };
    expect(() =>
      parseKolDomainSnapshotPayload({
        content: [child, CONTENT, other],
        evidence: [],
        claims: [],
        positionClaims: [],
      }),
    ).not.toThrow();
  });

  it("rejects exact-link provenance and availability mismatches", () => {
    const parse = (overrides: {
      evidence?: Record<string, unknown>;
      claim?: Record<string, unknown>;
      position?: Record<string, unknown>;
    }) =>
      parseKolDomainSnapshotPayload({
        content: [CONTENT],
        evidence: [overrides.evidence ?? EVIDENCE],
        claims: [overrides.claim ?? CLAIM],
        positionClaims: [overrides.position ?? POSITION_CLAIM],
      });

    expect(() => parse({ evidence: { ...EVIDENCE, source: "other-source" } })).toThrow(/source/);
    expect(() => parse({ evidence: { ...EVIDENCE, sourceVersion: "other-version" } })).toThrow(/source/);
    expect(() => parse({ claim: { ...CLAIM, contentAvailableTime: "2026-08-24T08:02:00Z" } })).toThrow(/contentAvailableTime/);
    expect(() =>
      parse({
        claim: {
          ...CLAIM,
          availableTime: "2026-08-24T08:03:00Z",
        },
      }),
    ).toThrow(/availability/);
    expect(() =>
      parse({
        claim: {
          ...CLAIM,
          evidence: [{ ...CLAIM.evidence[0], source: "other-source" }],
        },
      }),
    ).toThrow(/source/);
    expect(() =>
      parse({
        position: {
          ...POSITION_CLAIM,
          sourceVersion: "other-version",
        },
      }),
    ).toThrow(/source/);
    expect(() =>
      parse({
        position: {
          ...POSITION_CLAIM,
          availableTime: "2026-08-24T08:04:00Z",
        },
      }),
    ).toThrow(/availability/);
  });

  it("rejects invalid tombstones across all KOL runtime validators", () => {
    expect(validateKolContentPayload({ ...CONTENT, deleted: true, deletedAt: CONTENT.availableTime, deletionReason: null })).toMatchObject({ valid: false });
    expect(validateKolClaimPayload({ ...CLAIM, deleted: true, deletedAt: CLAIM.availableTime, deletionReason: null })).toMatchObject({ valid: false });
    expect(validateKolPositionClaimPayload({ ...POSITION_CLAIM, deleted: true, deletedAt: POSITION_CLAIM.availableTime, deletionReason: null })).toMatchObject({ valid: false });
    expect(validateKolClaimPayload({ ...CLAIM, deletionReason: "x".repeat(1001) })).toMatchObject({ valid: false });
  });

  it("deep-freezes aggregate records and nested evidence references", () => {
    const inputClaim = {
      ...CLAIM,
      evidence: CLAIM.evidence.map((reference) => ({ ...reference })),
    };
    const input = {
      content: [{ ...CONTENT }],
      evidence: [{ ...EVIDENCE }],
      claims: [inputClaim],
      positionClaims: [{ ...POSITION_CLAIM }],
    };
    const snapshot = parseKolDomainSnapshotPayload(input);
    inputClaim.evidence[0]!.source = "tampered-source";
    const snapshotClaim = snapshot.claims[0] as unknown as {
      readonly evidence: readonly Readonly<Record<string, unknown>>[];
    };
    expect(snapshotClaim.evidence[0]?.source).toBe(EVIDENCE.source);
    expect(Object.isFrozen(snapshot.claims[0])).toBe(true);
    expect(Object.isFrozen(snapshotClaim.evidence)).toBe(true);
    expect(Object.isFrozen(snapshotClaim.evidence[0])).toBe(true);
  });
});
