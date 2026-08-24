import { describe, expect, it } from "vitest";

import mediaSchema from "../../schemas/kol/media-text-evidence.json";
import { validateKolMediaTextEvidencePayload } from "./validators.js";

describe("KolMediaTextEvidence schema", () => {
  it("defines a closed, versioned ASR/OCR evidence contract", () => {
    expect(mediaSchema.title).toBe("KolMediaTextEvidence");
    expect(mediaSchema.additionalProperties).toBe(false);
    expect(mediaSchema.required).toEqual(
      expect.arrayContaining([
        "schemaVersion",
        "mediaManifest",
        "revisionId",
        "text",
        "segments",
        "language",
        "provenance",
        "availableTime",
      ]),
    );
    expect(mediaSchema.definitions).toMatchObject({
      MediaProcessorKind: { enum: ["ASR", "OCR"] },
      MediaKind: { enum: ["AUDIO", "VIDEO", "IMAGE"] },
    });
  });

  it("declares bounded locators, strict quality integers and tombstone metadata", () => {
    const definitions = mediaSchema.definitions as Record<string, Record<string, unknown>>;
    const segment = definitions.MediaTextSegment;
    if (segment === undefined) throw new Error("MediaTextSegment definition is missing");
    const properties = segment.properties as Record<string, Record<string, unknown>>;
    expect(properties.startOffset).toMatchObject({ type: "integer", minimum: 0 });
    expect(properties.endOffset).toMatchObject({ type: "integer", minimum: 1 });
    expect(properties.confidenceBps).toMatchObject({ type: "integer", minimum: 0, maximum: 10000 });
    expect(properties.qualityBps).toMatchObject({ type: "integer", minimum: 0, maximum: 10000 });
    expect(properties.bbox).toBeDefined();
    expect(mediaSchema.$comment).toMatch(/not.*Claim|not.*Trade/i);
  });

  it("runs the public validator for cross-field PIT and locator rules", () => {
    const valid = {
      schemaVersion: "kol-media-text-evidence-v1",
      evidenceId: "evidence-1",
      revisionId: "revision-1",
      previousRevisionId: null,
      mediaManifest: {
        contentId: "content-1",
        contentVersion: "content-v1",
        mediaId: "media-1",
        mediaVersion: "media-v1",
        revisionId: "media-revision-1",
        previousRevisionId: null,
        rawSha256: "a".repeat(64),
        mimeType: "audio/mpeg",
        byteSize: 4,
        mediaKind: "AUDIO",
        source: "fake",
        sourceVersion: "v1",
        licenseId: "license-1",
        usageRestriction: "research",
        authorized: true,
        inputAvailableTime: "2026-08-25T01:00:00Z",
        width: null,
        height: null,
        durationMs: 1000,
        deleted: false,
        deletedAt: null,
        deletionReason: null,
      },
      processorKind: "ASR",
      text: "test",
      language: "en-US",
      segments: [{
        text: "test",
        startOffset: 0,
        endOffset: 4,
        startMs: 0,
        endMs: 100,
        bbox: null,
        confidenceBps: 9000,
        qualityBps: 9000,
      }],
      confidenceBps: 9000,
      qualityBps: 9000,
      eventTime: null,
      publishTime: "2026-08-25T01:00:00Z",
      ingestTime: "2026-08-25T01:00:01Z",
      processingTime: "2026-08-25T01:01:00Z",
      availableTime: "2026-08-25T01:01:00Z",
      provenance: {
        pipelineVersion: "media-text-pipeline-v1",
        processorKind: "ASR",
        provider: "fake",
        model: "model",
        modelVersion: "v1",
        promptVersion: "not-applicable",
        configurationFingerprint: "b".repeat(64),
        policyFingerprint: "c".repeat(64),
        recognitionRunId: "run-1",
      },
      deleted: false,
      deletedAt: null,
      deletionReason: null,
    };
    expect(validateKolMediaTextEvidencePayload(valid).valid).toBe(true);
    expect(validateKolMediaTextEvidencePayload({ ...valid, availableTime: "2026-08-25T01:00:00Z" }).valid).toBe(false);
    expect(validateKolMediaTextEvidencePayload({ ...valid, unknown: true }).valid).toBe(false);
  });
});
