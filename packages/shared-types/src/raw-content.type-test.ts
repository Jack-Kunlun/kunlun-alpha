import type { RawContent } from "./index";

/**
 * Negative type-test for the closed RawContent contract.
 *
 * RawContent must reject unknown fields at compile time (matching the JSON
 * Schema `additionalProperties: false` and the generated Pydantic
 * `extra="forbid"`). A catch-all index signature would silently accept any
 * extra field, so `@ts-expect-error` below must actually be consumed.
 */

const valid: RawContent = {
  contentType: "NEWS",
  recordId: "rec-1",
  versionId: "0".repeat(64),
  url: "https://example.com/news/1",
  title: "标题",
  body: "正文",
  publishTime: "2026-08-21T01:00:00Z",
  ingestTime: "2026-08-21T01:05:00Z",
  availableTime: "2026-08-21T01:05:00Z",
  fingerprint: "a".repeat(64),
  fingerprintAlgorithmVersion: "sha256-v1",
  source: { sourceId: "cninfo", sourceVersion: "v1", evidenceId: "evt-001" },
  license: { licenseId: "COMMERCIAL", usageRestriction: "internal-only", authorized: true },
  deleted: false,
  deletedAt: null,
};

const invalid: RawContent = {
  ...valid,
  // @ts-expect-error RawContent must reject unknown extra fields
  unexpectedField: "forbidden",
};

export {};
