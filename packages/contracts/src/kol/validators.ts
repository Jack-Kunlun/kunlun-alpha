/** Runtime validators for untrusted KOL content and claim payloads. */

import { parseInstrumentCode } from "../instrument/code-parser.js";

export type ValidationResult = {
  valid: boolean;
  errors: string[];
};

type JsonRecord = Record<string, unknown>;

export const KOL_ALGORITHM_VERSION = "kol-domain-v1" as const;
export const KOL_CONTENT_SCHEMA_VERSION = "kol-content-v1" as const;
export const KOL_MENTION_SCHEMA_VERSION = "kol-mention-v1" as const;
export const KOL_EVIDENCE_SCHEMA_VERSION = "kol-evidence-v1" as const;
export const KOL_CLAIM_SCHEMA_VERSION = "kol-claim-v1" as const;
export const KOL_POSITION_CLAIM_SCHEMA_VERSION = "kol-position-claim-v1" as const;
export const KOL_CONTENT_FINGERPRINT_ALGORITHM_VERSION = "sha256-kol-content-v1" as const;
export const KOL_EVIDENCE_GRADE_VERSION = "evidence-grade-v1" as const;
export const APPROVED_REVIEW_SEMANTICS = "PUBLIC_WORDING_REVIEWED_NOT_FACT_OR_EXECUTION" as const;
export const NON_EXECUTABLE_POSITION_CLAIM = "NON_EXECUTABLE_POSITION_CLAIM" as const;
export const KOL_MEDIA_TEXT_EVIDENCE_SCHEMA_VERSION = "kol-media-text-evidence-v1" as const;
export const MEDIA_RECOGNITION_CANDIDATE_SCHEMA_VERSION = "media-recognition-candidate-v1" as const;

const INSTANT_PATTERN = /T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const FINGERPRINT_PATTERN = /^[0-9a-f]{64}$/;
const CLAIM_STATEMENT_KINDS = new Set(["DIRECT", "QUOTE", "PARAPHRASE", "AMBIGUOUS"]);
const CLAIM_DIRECTIONS = new Set(["BULLISH", "BEARISH", "NEUTRAL"]);
const ATTRIBUTIONS = new Set(["SELF", "QUOTED", "REPORTED", "UNKNOWN"]);
const UNCERTAINTIES = new Set(["NONE", "AMBIGUOUS", "CONDITIONAL", "UNVERIFIED"]);
const REVIEW_STATUSES = new Set(["UNREVIEWED", "IN_REVIEW", "APPROVED", "REJECTED"]);
const EVIDENCE_GRADES = new Set([
  "PRIMARY_SOURCE",
  "SECONDARY_SOURCE",
  "TERTIARY_SOURCE",
  "UNCLASSIFIED",
]);

function record(value: unknown): JsonRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonRecord)
    : null;
}

function result(errors: string[]): ValidationResult {
  return { valid: errors.length === 0, errors };
}

function closed(payload: JsonRecord, allowed: readonly string[], errors: string[]): void {
  const allowedSet = new Set(allowed);
  for (const key of Object.keys(payload).sort()) {
    if (!allowedSet.has(key)) errors.push(`unknown field: ${key}`);
  }
}

function requiredString(
  payload: JsonRecord,
  field: string,
  errors: string[],
  maxLength = 256,
): string | undefined {
  const value = payload[field];
  if (typeof value !== "string" || value.trim().length === 0) {
    errors.push(`${field} must be a non-empty string`);
    return undefined;
  }
  if (value.length > maxLength) errors.push(`${field} exceeds maximum length ${maxLength}`);
  return value;
}

function optionalString(
  payload: JsonRecord,
  field: string,
  errors: string[],
  maxLength = 256,
): string | null | undefined {
  const value = payload[field];
  if (value === null) return null;
  if (typeof value !== "string" || value.trim().length === 0) {
    errors.push(`${field} must be a non-empty string or null`);
    return undefined;
  }
  if (value.length > maxLength) errors.push(`${field} exceeds maximum length ${maxLength}`);
  return value;
}

function enumString(
  payload: JsonRecord,
  field: string,
  allowed: ReadonlySet<string>,
  errors: string[],
): string | undefined {
  const value = requiredString(payload, field, errors);
  if (value !== undefined && !allowed.has(value)) errors.push(`${field} has an invalid value`);
  return value;
}

function instant(value: unknown, field: string, errors: string[]): number | undefined {
  if (typeof value !== "string" || !INSTANT_PATTERN.test(value)) {
    errors.push(`${field} must be a timezone-aware RFC 3339 instant`);
    return undefined;
  }
  if (value.length > 64) errors.push(`${field} exceeds maximum length 64`);
  const milliseconds = Date.parse(value);
  if (Number.isNaN(milliseconds)) errors.push(`${field} must be a valid instant`);
  return Number.isNaN(milliseconds) ? undefined : milliseconds;
}

function optionalInstant(
  payload: JsonRecord,
  field: string,
  errors: string[],
): number | null | undefined {
  if (payload[field] === null) return null;
  return instant(payload[field], field, errors);
}

function revisionChain(payload: JsonRecord, errors: string[]): void {
  const revisionId = requiredString(payload, "revisionId", errors);
  const previousRevisionId = optionalString(payload, "previousRevisionId", errors);
  if (revisionId !== undefined && previousRevisionId === revisionId) {
    errors.push("previousRevisionId must differ from revisionId");
  }
}

function timeChain(
  payload: JsonRecord,
  errors: string[],
): {
  publish: number | undefined;
  ingest: number | undefined;
  processing: number | undefined;
  available: number | undefined;
} {
  const publish = instant(payload.publishTime, "publishTime", errors);
  const ingest = instant(payload.ingestTime, "ingestTime", errors);
  const processing = instant(payload.processingTime, "processingTime", errors);
  const available = instant(payload.availableTime, "availableTime", errors);
  if (publish !== undefined && ingest !== undefined && publish > ingest) {
    errors.push("publishTime must be <= ingestTime");
  }
  if (ingest !== undefined && processing !== undefined && ingest > processing) {
    errors.push("ingestTime must be <= processingTime");
  }
  if (processing !== undefined && available !== undefined && processing > available) {
    errors.push("processingTime must be <= availableTime");
  }
  return { publish, ingest, processing, available };
}

function deletion(payload: JsonRecord, available: number | undefined, errors: string[]): void {
  const deleted = payload.deleted;
  if (typeof deleted !== "boolean") errors.push("deleted must be a boolean");
  const deletedAt = optionalInstant(payload, "deletedAt", errors);
  const reason = optionalString(payload, "deletionReason", errors, 1000);
  const hasDeletedAt = deletedAt !== null && deletedAt !== undefined;
  const hasReason = reason !== null && reason !== undefined;
  if (deleted === true && (!hasDeletedAt || !hasReason)) {
    errors.push("deleted content must have deletedAt and deletionReason");
  }
  if (deleted === false && (hasDeletedAt || hasReason)) {
    errors.push("non-deleted content must not have deletion metadata");
  }
  if (hasDeletedAt && deletedAt !== undefined && available !== undefined && deletedAt < available) {
    errors.push("deletedAt must be >= availableTime");
  }
}

function canonicalInstrument(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const parts = value.split(".");
  if (parts.length !== 2) return false;
  const code = parts[0];
  const exchange = parts[1];
  if (code === undefined || exchange === undefined || !["SH", "SZ", "BJ"].includes(exchange)) {
    return false;
  }
  const parsed = parseInstrumentCode(code);
  return parsed !== null && parsed.unifiedCode === value && parsed.exchange === exchange;
}

const MEDIA_PROCESSORS = new Set(["ASR", "OCR"]);
const MEDIA_KINDS = new Set(["AUDIO", "VIDEO", "IMAGE"]);
const MEDIA_MIME_PREFIX: Record<string, string> = {
  AUDIO: "audio/",
  VIDEO: "video/",
  IMAGE: "image/",
};

function strictInteger(
  value: unknown,
  field: string,
  errors: string[],
  min: number,
  max: number,
): number | undefined {
  if (typeof value !== "number" || !Number.isInteger(value) || !Number.isFinite(value)) {
    errors.push(`${field} must be an integer`);
    return undefined;
  }
  if (value < min || value > max) errors.push(`${field} must be between ${min} and ${max}`);
  return value;
}

function mediaBBox(
  value: unknown,
  field: string,
  errors: string[],
): { x: number; y: number; width: number; height: number } | null | undefined {
  if (value === null) return null;
  const bbox = record(value);
  if (bbox === null) {
    errors.push(`${field} must be an object or null`);
    return undefined;
  }
  closed(bbox, ["x", "y", "width", "height"], errors);
  const x = strictInteger(bbox.x, `${field}.x`, errors, 0, 100000);
  const y = strictInteger(bbox.y, `${field}.y`, errors, 0, 100000);
  const width = strictInteger(bbox.width, `${field}.width`, errors, 1, 100000);
  const height = strictInteger(bbox.height, `${field}.height`, errors, 1, 100000);
  if (x === undefined || y === undefined || width === undefined || height === undefined)
    return undefined;
  return { x, y, width, height };
}

function validateMediaManifest(value: unknown, errors: string[]): JsonRecord | null {
  const manifest = record(value);
  if (manifest === null) {
    errors.push("mediaManifest must be an object");
    return null;
  }
  closed(
    manifest,
    [
      "contentId",
      "contentVersion",
      "mediaId",
      "mediaVersion",
      "revisionId",
      "previousRevisionId",
      "rawSha256",
      "mimeType",
      "byteSize",
      "mediaKind",
      "source",
      "sourceVersion",
      "licenseId",
      "usageRestriction",
      "authorized",
      "inputAvailableTime",
      "width",
      "height",
      "durationMs",
      "deleted",
      "deletedAt",
      "deletionReason",
    ],
    errors,
  );
  requiredString(manifest, "contentId", errors);
  requiredString(manifest, "contentVersion", errors);
  requiredString(manifest, "mediaId", errors);
  requiredString(manifest, "mediaVersion", errors);
  revisionChain(manifest, errors);
  const digest = requiredString(manifest, "rawSha256", errors, 64);
  if (digest !== undefined && !FINGERPRINT_PATTERN.test(digest))
    errors.push("rawSha256 must be lowercase SHA-256");
  const mime = requiredString(manifest, "mimeType", errors, 128);
  const kind = enumString(manifest, "mediaKind", MEDIA_KINDS, errors);
  const mimePrefix =
    kind === "AUDIO" || kind === "VIDEO" || kind === "IMAGE" ? MEDIA_MIME_PREFIX[kind] : undefined;
  if (mime !== undefined && mimePrefix !== undefined && !mime.startsWith(mimePrefix))
    errors.push("mimeType does not match mediaKind");
  strictInteger(manifest.byteSize, "byteSize", errors, 1, 1_000_000_000);
  requiredString(manifest, "source", errors);
  requiredString(manifest, "sourceVersion", errors);
  requiredString(manifest, "licenseId", errors);
  requiredString(manifest, "usageRestriction", errors, 1000);
  if (typeof manifest.authorized !== "boolean") errors.push("authorized must be a boolean");
  const inputAvailable = instant(manifest.inputAvailableTime, "inputAvailableTime", errors);
  const width =
    manifest.width === null ? null : strictInteger(manifest.width, "width", errors, 1, 100000);
  const height =
    manifest.height === null ? null : strictInteger(manifest.height, "height", errors, 1, 100000);
  if ((width === null) !== (height === null))
    errors.push("width and height must be both null or present");
  const duration =
    manifest.durationMs === null
      ? null
      : strictInteger(manifest.durationMs, "durationMs", errors, 1, 864000000);
  if (kind === "IMAGE" && (width === null || height === null))
    errors.push("image media requires dimensions");
  if ((kind === "AUDIO" || kind === "VIDEO") && duration === null)
    errors.push("audio/video media requires durationMs");
  deletion(manifest, inputAvailable, errors);
  return manifest;
}

export function validateKolMediaTextEvidencePayload(input: unknown): ValidationResult {
  const payload = record(input);
  if (payload === null) return result(["media evidence must be an object"]);
  const errors: string[] = [];
  closed(
    payload,
    [
      "schemaVersion",
      "evidenceId",
      "revisionId",
      "previousRevisionId",
      "mediaManifest",
      "processorKind",
      "text",
      "language",
      "segments",
      "confidenceBps",
      "qualityBps",
      "eventTime",
      "publishTime",
      "ingestTime",
      "processingTime",
      "availableTime",
      "provenance",
      "deleted",
      "deletedAt",
      "deletionReason",
    ],
    errors,
  );
  if (payload.schemaVersion !== KOL_MEDIA_TEXT_EVIDENCE_SCHEMA_VERSION)
    errors.push("unsupported media evidence schema version");
  requiredString(payload, "evidenceId", errors);
  revisionChain(payload, errors);
  const manifest = validateMediaManifest(payload.mediaManifest, errors);
  const processor = enumString(payload, "processorKind", MEDIA_PROCESSORS, errors);
  const text = requiredString(payload, "text", errors, 2_000_000);
  const language = requiredString(payload, "language", errors, 35);
  if (language !== undefined && !/^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/.test(language))
    errors.push("language must be BCP-47");
  strictInteger(payload.confidenceBps, "confidenceBps", errors, 0, 10000);
  strictInteger(payload.qualityBps, "qualityBps", errors, 0, 10000);
  optionalInstant(payload, "eventTime", errors);
  const chain = timeChain(payload, errors);
  if (manifest !== null && chain.available !== undefined && chain.processing !== undefined) {
    const manifestAvailable = instant(manifest.inputAvailableTime, "inputAvailableTime", errors);
    if (
      manifestAvailable !== undefined &&
      chain.available !== Math.max(manifestAvailable, chain.processing)
    )
      errors.push("availableTime must equal max(inputAvailableTime, processingTime)");
  }
  deletion(payload, chain.available, errors);
  const provenance = record(payload.provenance);
  if (provenance === null) errors.push("provenance must be an object");
  else {
    closed(
      provenance,
      [
        "pipelineVersion",
        "processorKind",
        "provider",
        "model",
        "modelVersion",
        "promptVersion",
        "configurationFingerprint",
        "policyFingerprint",
        "recognitionRunId",
      ],
      errors,
    );
    requiredString(provenance, "pipelineVersion", errors, 128);
    enumString(provenance, "processorKind", MEDIA_PROCESSORS, errors);
    requiredString(provenance, "provider", errors);
    requiredString(provenance, "model", errors);
    requiredString(provenance, "modelVersion", errors);
    requiredString(provenance, "promptVersion", errors);
    const config = requiredString(provenance, "configurationFingerprint", errors, 64);
    if (config !== undefined && !FINGERPRINT_PATTERN.test(config))
      errors.push("configurationFingerprint must be lowercase SHA-256");
    const policy = requiredString(provenance, "policyFingerprint", errors, 64);
    if (policy !== undefined && !FINGERPRINT_PATTERN.test(policy))
      errors.push("policyFingerprint must be lowercase SHA-256");
    requiredString(provenance, "recognitionRunId", errors);
    if (processor !== undefined && provenance.processorKind !== processor)
      errors.push("provenance processorKind must match");
  }
  const segments = payload.segments;
  if (!Array.isArray(segments) || segments.length === 0)
    errors.push("segments must be a non-empty array");
  else if (segments.length > 100000) errors.push("segments exceeds maximum length 100000");
  if (
    Array.isArray(segments) &&
    text !== undefined &&
    manifest !== null &&
    processor !== undefined
  ) {
    for (const [index, rawSegment] of segments.entries()) {
      const segment = record(rawSegment);
      if (segment === null) {
        errors.push(`segments[${index}] must be an object`);
        continue;
      }
      closed(
        segment,
        [
          "text",
          "startOffset",
          "endOffset",
          "startMs",
          "endMs",
          "bbox",
          "frameIdentity",
          "confidenceBps",
          "qualityBps",
        ],
        errors,
      );
      const segmentText = requiredString(segment, "text", errors, 200000);
      const startOffset = strictInteger(
        segment.startOffset,
        `segments[${index}].startOffset`,
        errors,
        0,
        2000000,
      );
      const endOffset = strictInteger(
        segment.endOffset,
        `segments[${index}].endOffset`,
        errors,
        1,
        2000000,
      );
      if (segmentText !== undefined && startOffset !== undefined && endOffset !== undefined) {
        const codePoints = Array.from(text);
        if (
          endOffset > codePoints.length ||
          endOffset <= startOffset ||
          codePoints.slice(startOffset, endOffset).join("") !== segmentText
        )
          errors.push(`segments[${index}] offsets do not match text`);
      }
      const startMs =
        segment.startMs === null
          ? null
          : strictInteger(segment.startMs, `segments[${index}].startMs`, errors, 0, 864000000);
      const endMs =
        segment.endMs === null
          ? null
          : strictInteger(segment.endMs, `segments[${index}].endMs`, errors, 1, 864000000);
      if (
        (startMs === null) !== (endMs === null) ||
        (typeof startMs === "number" && typeof endMs === "number" && endMs <= startMs)
      )
        errors.push(`segments[${index}] invalid time range`);
      const bbox = mediaBBox(segment.bbox, `segments[${index}].bbox`, errors);
      if (
        segment.frameIdentity !== null &&
        segment.frameIdentity !== undefined &&
        (typeof segment.frameIdentity !== "string" ||
          !FINGERPRINT_PATTERN.test(segment.frameIdentity))
      )
        errors.push(`segments[${index}].frameIdentity must be lowercase SHA-256`);
      strictInteger(segment.confidenceBps, `segments[${index}].confidenceBps`, errors, 0, 10000);
      strictInteger(segment.qualityBps, `segments[${index}].qualityBps`, errors, 0, 10000);
      if (
        bbox !== undefined &&
        bbox !== null &&
        typeof manifest.width === "number" &&
        typeof manifest.height === "number" &&
        (bbox.x + bbox.width > manifest.width || bbox.y + bbox.height > manifest.height)
      )
        errors.push(`segments[${index}] bbox is outside media dimensions`);
      const kind = manifest.mediaKind;
      if (
        processor === "ASR" &&
        ((kind !== "AUDIO" && kind !== "VIDEO") || startMs === null || endMs === null)
      )
        errors.push(`segments[${index}] ASR requires audio/video timecode`);
      if (processor === "OCR" && kind === "IMAGE" && bbox === null)
        errors.push(`segments[${index}] image OCR requires bbox`);
      if (processor === "OCR" && kind === "VIDEO" && startMs === null && bbox === null)
        errors.push(`segments[${index}] video OCR requires time or bbox`);
    }
  }
  return result(errors);
}

const SHA256_K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

function rotr(value: number, bits: number): number {
  return (value >>> bits) | (value << (32 - bits));
}

function utf8Bytes(value: string): Uint8Array {
  const bytes: number[] = [];
  for (let index = 0; index < value.length; index += 1) {
    let codePoint = value.codePointAt(index) ?? 0xfffd;
    if (codePoint >= 0xd800 && codePoint <= 0xdfff) codePoint = 0xfffd;
    if (codePoint > 0xffff) index += 1;
    if (codePoint <= 0x7f) {
      bytes.push(codePoint);
    } else if (codePoint <= 0x7ff) {
      bytes.push(0xc0 | (codePoint >>> 6), 0x80 | (codePoint & 0x3f));
    } else if (codePoint <= 0xffff) {
      bytes.push(
        0xe0 | (codePoint >>> 12),
        0x80 | ((codePoint >>> 6) & 0x3f),
        0x80 | (codePoint & 0x3f),
      );
    } else {
      bytes.push(
        0xf0 | (codePoint >>> 18),
        0x80 | ((codePoint >>> 12) & 0x3f),
        0x80 | ((codePoint >>> 6) & 0x3f),
        0x80 | (codePoint & 0x3f),
      );
    }
  }
  return Uint8Array.from(bytes);
}

export function computeKolContentFingerprint(title: string, body: string): string {
  const bytes = utf8Bytes(`${title}\u0000${body}`);
  const blockLength = (bytes.length + 9 + 63) & ~63;
  const padded = new Uint8Array(blockLength);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  let bitLength = BigInt(bytes.length) * 8n;
  for (let index = 0; index < 8; index += 1) {
    padded[blockLength - 1 - index] = Number(bitLength & 0xffn);
    bitLength >>= 8n;
  }

  const state = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ]);
  for (let offset = 0; offset < padded.length; offset += 64) {
    const schedule = new Uint32Array(64);
    for (let index = 0; index < 16; index += 1) {
      const position = offset + index * 4;
      schedule[index] =
        (((padded[position] ?? 0) << 24) |
          ((padded[position + 1] ?? 0) << 16) |
          ((padded[position + 2] ?? 0) << 8) |
          (padded[position + 3] ?? 0)) >>>
        0;
    }
    for (let index = 16; index < 64; index += 1) {
      const previous15 = schedule[index - 15] ?? 0;
      const previous2 = schedule[index - 2] ?? 0;
      const s0 = rotr(previous15, 7) ^ rotr(previous15, 18) ^ (previous15 >>> 3);
      const s1 = rotr(previous2, 17) ^ rotr(previous2, 19) ^ (previous2 >>> 10);
      schedule[index] = ((schedule[index - 16] ?? 0) + s0 + (schedule[index - 7] ?? 0) + s1) >>> 0;
    }
    let a = state[0] ?? 0;
    let b = state[1] ?? 0;
    let c = state[2] ?? 0;
    let d = state[3] ?? 0;
    let e = state[4] ?? 0;
    let f = state[5] ?? 0;
    let g = state[6] ?? 0;
    let h = state[7] ?? 0;
    for (let index = 0; index < 64; index += 1) {
      const s1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const choose = (e & f) ^ (~e & g);
      const temp1 = (h + s1 + choose + (SHA256_K[index] ?? 0) + (schedule[index] ?? 0)) >>> 0;
      const s0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (s0 + majority) >>> 0;
      [h, g, f, e, d, c, b, a] = [g, f, e, (d + temp1) >>> 0, c, b, a, (temp1 + temp2) >>> 0];
    }
    state[0] = ((state[0] ?? 0) + a) >>> 0;
    state[1] = ((state[1] ?? 0) + b) >>> 0;
    state[2] = ((state[2] ?? 0) + c) >>> 0;
    state[3] = ((state[3] ?? 0) + d) >>> 0;
    state[4] = ((state[4] ?? 0) + e) >>> 0;
    state[5] = ((state[5] ?? 0) + f) >>> 0;
    state[6] = ((state[6] ?? 0) + g) >>> 0;
    state[7] = ((state[7] ?? 0) + h) >>> 0;
  }
  return Array.from(state, (value) => value.toString(16).padStart(8, "0")).join("");
}

const CONTENT_FIELDS = [
  "schemaVersion",
  "contentId",
  "contentVersion",
  "revisionId",
  "previousRevisionId",
  "kolId",
  "contentType",
  "title",
  "body",
  "contentFingerprint",
  "contentFingerprintAlgorithmVersion",
  "eventTime",
  "publishTime",
  "ingestTime",
  "processingTime",
  "availableTime",
  "source",
  "sourceVersion",
  "deleted",
  "deletedAt",
  "deletionReason",
] as const;

export function validateKolContentPayload(input: unknown): ValidationResult {
  const payload = record(input);
  if (payload === null) return result(["payload must be an object"]);
  const errors: string[] = [];
  closed(payload, CONTENT_FIELDS, errors);
  if (payload.schemaVersion !== KOL_CONTENT_SCHEMA_VERSION) errors.push("invalid schemaVersion");
  requiredString(payload, "contentId", errors);
  requiredString(payload, "contentVersion", errors);
  revisionChain(payload, errors);
  requiredString(payload, "kolId", errors);
  enumString(
    payload,
    "contentType",
    new Set(["POST", "ARTICLE", "VIDEO", "AUDIO", "COMMENT", "OTHER"]),
    errors,
  );
  const title = requiredString(payload, "title", errors, 10000);
  const body = requiredString(payload, "body", errors, 1000000);
  if (
    typeof payload.contentFingerprint !== "string" ||
    !FINGERPRINT_PATTERN.test(payload.contentFingerprint)
  ) {
    errors.push("contentFingerprint must be lowercase SHA-256 hex");
  } else if (payload.contentFingerprint !== computeKolContentFingerprint(title ?? "", body ?? "")) {
    errors.push("contentFingerprint does not match title and body");
  }
  if (payload.contentFingerprintAlgorithmVersion !== KOL_CONTENT_FINGERPRINT_ALGORITHM_VERSION) {
    errors.push("invalid contentFingerprintAlgorithmVersion");
  }
  optionalInstant(payload, "eventTime", errors);
  const chain = timeChain(payload, errors);
  requiredString(payload, "source", errors);
  requiredString(payload, "sourceVersion", errors);
  deletion(payload, chain.available, errors);
  return result(errors);
}

const MENTION_FIELDS = [
  "schemaVersion",
  "mentionId",
  "revisionId",
  "previousRevisionId",
  "contentId",
  "contentVersion",
  "kolId",
  "mentionType",
  "surfaceText",
  "startOffset",
  "endOffset",
  "availableTime",
  "source",
  "sourceVersion",
] as const;

export function validateKolMentionPayload(input: unknown): ValidationResult {
  const payload = record(input);
  if (payload === null) return result(["payload must be an object"]);
  const errors: string[] = [];
  closed(payload, MENTION_FIELDS, errors);
  if (payload.schemaVersion !== KOL_MENTION_SCHEMA_VERSION) errors.push("invalid schemaVersion");
  requiredString(payload, "mentionId", errors);
  revisionChain(payload, errors);
  requiredString(payload, "contentId", errors);
  requiredString(payload, "contentVersion", errors);
  requiredString(payload, "kolId", errors);
  enumString(
    payload,
    "mentionType",
    new Set(["INSTRUMENT", "PERSON", "ORGANIZATION", "TOPIC", "OTHER"]),
    errors,
  );
  requiredString(payload, "surfaceText", errors, 1000);
  if (
    typeof payload.startOffset !== "number" ||
    !Number.isInteger(payload.startOffset) ||
    payload.startOffset < 0
  ) {
    errors.push("startOffset must be a non-negative integer");
  }
  if (
    typeof payload.endOffset !== "number" ||
    !Number.isInteger(payload.endOffset) ||
    payload.endOffset < 1
  ) {
    errors.push("endOffset must be a positive integer");
  }
  if (typeof payload.startOffset === "number" && payload.startOffset > 1000000) {
    errors.push("startOffset exceeds maximum 1000000");
  }
  if (typeof payload.endOffset === "number" && payload.endOffset > 1000000) {
    errors.push("endOffset exceeds maximum 1000000");
  }
  if (
    typeof payload.startOffset === "number" &&
    typeof payload.endOffset === "number" &&
    payload.endOffset <= payload.startOffset
  ) {
    errors.push("endOffset must be greater than startOffset");
  }
  instant(payload.availableTime, "availableTime", errors);
  requiredString(payload, "source", errors);
  requiredString(payload, "sourceVersion", errors);
  return result(errors);
}

const EVIDENCE_FIELDS = [
  "schemaVersion",
  "evidenceId",
  "revisionId",
  "previousRevisionId",
  "contentId",
  "contentVersion",
  "contentAvailableTime",
  "source",
  "sourceVersion",
  "locatorType",
  "locator",
  "excerpt",
  "evidenceGrade",
  "evidenceGradeVersion",
  "availableTime",
] as const;

export function validateKolEvidencePayload(input: unknown): ValidationResult {
  const payload = record(input);
  if (payload === null) return result(["payload must be an object"]);
  const errors: string[] = [];
  closed(payload, EVIDENCE_FIELDS, errors);
  if (payload.schemaVersion !== KOL_EVIDENCE_SCHEMA_VERSION) errors.push("invalid schemaVersion");
  requiredString(payload, "evidenceId", errors);
  revisionChain(payload, errors);
  requiredString(payload, "contentId", errors);
  requiredString(payload, "contentVersion", errors);
  const contentAvailable = instant(payload.contentAvailableTime, "contentAvailableTime", errors);
  requiredString(payload, "source", errors);
  requiredString(payload, "sourceVersion", errors);
  enumString(payload, "locatorType", new Set(["URL", "TEXT_RANGE", "TIME_RANGE", "PAGE"]), errors);
  requiredString(payload, "locator", errors, 2048);
  requiredString(payload, "excerpt", errors, 4000);
  enumString(payload, "evidenceGrade", EVIDENCE_GRADES, errors);
  if (payload.evidenceGradeVersion !== KOL_EVIDENCE_GRADE_VERSION) {
    errors.push("invalid evidenceGradeVersion");
  }
  const available = instant(payload.availableTime, "availableTime", errors);
  if (contentAvailable !== undefined && available !== undefined && contentAvailable > available) {
    errors.push("contentAvailableTime must be <= availableTime");
  }
  return result(errors);
}

const EVIDENCE_REFERENCE_FIELDS = [
  "evidenceId",
  "evidenceRevisionId",
  "contentId",
  "contentVersion",
  "contentAvailableTime",
  "evidenceAvailableTime",
  "source",
  "sourceVersion",
] as const;

function validateEvidenceReference(
  value: unknown,
  index: number,
  claimContentId: string | undefined,
  claimContentVersion: string | undefined,
  claimAvailable: number | undefined,
  errors: string[],
): void {
  const reference = record(value);
  if (reference === null) {
    errors.push(`evidence[${index}] must be an object`);
    return;
  }
  closed(reference, EVIDENCE_REFERENCE_FIELDS, errors);
  requiredString(reference, "evidenceId", errors);
  requiredString(reference, "evidenceRevisionId", errors);
  const contentId = requiredString(reference, "contentId", errors);
  const contentVersion = requiredString(reference, "contentVersion", errors);
  const contentAvailable = instant(
    reference.contentAvailableTime,
    `evidence[${index}].contentAvailableTime`,
    errors,
  );
  const evidenceAvailable = instant(
    reference.evidenceAvailableTime,
    `evidence[${index}].evidenceAvailableTime`,
    errors,
  );
  requiredString(reference, "source", errors);
  requiredString(reference, "sourceVersion", errors);
  if (contentId !== undefined && claimContentId !== undefined && contentId !== claimContentId) {
    errors.push(`evidence[${index}] contentId must match claim contentId`);
  }
  if (
    contentVersion !== undefined &&
    claimContentVersion !== undefined &&
    contentVersion !== claimContentVersion
  ) {
    errors.push(`evidence[${index}] contentVersion must match claim contentVersion`);
  }
  if (
    contentAvailable !== undefined &&
    evidenceAvailable !== undefined &&
    contentAvailable > evidenceAvailable
  ) {
    errors.push(`evidence[${index}] contentAvailableTime must be <= evidenceAvailableTime`);
  }
  if (
    contentAvailable !== undefined &&
    claimAvailable !== undefined &&
    contentAvailable > claimAvailable
  ) {
    errors.push(`evidence[${index}] is not available at claim availableTime`);
  }
  if (
    evidenceAvailable !== undefined &&
    claimAvailable !== undefined &&
    evidenceAvailable > claimAvailable
  ) {
    errors.push(`evidence[${index}] is not available at claim availableTime`);
  }
}

const CLAIM_FIELDS = [
  "schemaVersion",
  "claimId",
  "revisionId",
  "previousRevisionId",
  "contentId",
  "contentVersion",
  "contentAvailableTime",
  "kolId",
  "statement",
  "statementKind",
  "instrumentId",
  "direction",
  "attribution",
  "uncertainty",
  "confidenceBps",
  "reviewStatus",
  "eventTime",
  "publishTime",
  "ingestTime",
  "processingTime",
  "availableTime",
  "source",
  "sourceVersion",
  "evidence",
  "deleted",
  "deletedAt",
  "deletionReason",
] as const;

export function validateKolClaimPayload(input: unknown): ValidationResult {
  const payload = record(input);
  if (payload === null) return result(["payload must be an object"]);
  const errors: string[] = [];
  closed(payload, CLAIM_FIELDS, errors);
  if (payload.schemaVersion !== KOL_CLAIM_SCHEMA_VERSION) errors.push("invalid schemaVersion");
  requiredString(payload, "claimId", errors);
  revisionChain(payload, errors);
  const contentId = requiredString(payload, "contentId", errors);
  const contentVersion = requiredString(payload, "contentVersion", errors);
  const contentAvailable = instant(payload.contentAvailableTime, "contentAvailableTime", errors);
  requiredString(payload, "kolId", errors);
  requiredString(payload, "statement", errors, 10000);
  if (!canonicalInstrument(payload.instrumentId)) {
    errors.push("instrumentId must use canonical unified code form");
  }
  enumString(payload, "direction", CLAIM_DIRECTIONS, errors);
  const attribution = enumString(payload, "attribution", ATTRIBUTIONS, errors);
  const uncertainty = enumString(payload, "uncertainty", UNCERTAINTIES, errors);
  if (
    typeof payload.confidenceBps !== "number" ||
    !Number.isInteger(payload.confidenceBps) ||
    payload.confidenceBps < 0 ||
    payload.confidenceBps > 10000
  ) {
    errors.push("confidenceBps must be an integer between 0 and 10000");
  }
  const statementKind = enumString(payload, "statementKind", CLAIM_STATEMENT_KINDS, errors);
  if (statementKind === "QUOTE" && attribution !== "QUOTED" && attribution !== "REPORTED") {
    errors.push("QUOTE claims require QUOTED or REPORTED attribution");
  }
  if (statementKind === "AMBIGUOUS" && uncertainty === "NONE") {
    errors.push("AMBIGUOUS claims require non-NONE uncertainty");
  }
  enumString(payload, "reviewStatus", REVIEW_STATUSES, errors);
  instant(payload.eventTime, "eventTime", errors);
  const chain = timeChain(payload, errors);
  requiredString(payload, "source", errors);
  requiredString(payload, "sourceVersion", errors);
  if (!Array.isArray(payload.evidence) || payload.evidence.length === 0) {
    errors.push("evidence must contain at least one reference");
  } else {
    const identities = new Set<string>();
    payload.evidence.forEach((value, index) => {
      const reference = record(value);
      if (reference !== null) {
        const evidenceId = typeof reference.evidenceId === "string" ? reference.evidenceId : "";
        const revisionId =
          typeof reference.evidenceRevisionId === "string" ? reference.evidenceRevisionId : "";
        const identity = `${evidenceId}\u0000${revisionId}`;
        if (identities.has(identity)) errors.push("evidence references must be unique");
        identities.add(identity);
      }
      validateEvidenceReference(value, index, contentId, contentVersion, chain.available, errors);
    });
  }
  deletion(payload, chain.available, errors);
  if (
    contentAvailable !== undefined &&
    chain.available !== undefined &&
    contentAvailable > chain.available
  ) {
    errors.push("claim availableTime must include contentAvailableTime");
  }
  return result(errors);
}

const POSITION_FIELDS = [
  "schemaVersion",
  "positionClaimId",
  "revisionId",
  "previousRevisionId",
  "claimId",
  "claimRevisionId",
  "kolId",
  "instrumentId",
  "position",
  "timeHorizon",
  "executionSemantics",
  "confidenceBps",
  "reviewStatus",
  "eventTime",
  "publishTime",
  "ingestTime",
  "processingTime",
  "availableTime",
  "source",
  "sourceVersion",
  "deleted",
  "deletedAt",
  "deletionReason",
] as const;

export function validateKolPositionClaimPayload(input: unknown): ValidationResult {
  const payload = record(input);
  if (payload === null) return result(["payload must be an object"]);
  const errors: string[] = [];
  closed(payload, POSITION_FIELDS, errors);
  if (payload.schemaVersion !== KOL_POSITION_CLAIM_SCHEMA_VERSION)
    errors.push("invalid schemaVersion");
  requiredString(payload, "positionClaimId", errors);
  revisionChain(payload, errors);
  requiredString(payload, "claimId", errors);
  requiredString(payload, "claimRevisionId", errors);
  requiredString(payload, "kolId", errors);
  if (!canonicalInstrument(payload.instrumentId)) {
    errors.push("instrumentId must use canonical unified code form");
  }
  enumString(payload, "position", new Set(["LONG", "SHORT", "FLAT"]), errors);
  enumString(
    payload,
    "timeHorizon",
    new Set(["INTRADAY", "SWING", "LONG_TERM", "UNSPECIFIED"]),
    errors,
  );
  if (payload.executionSemantics !== NON_EXECUTABLE_POSITION_CLAIM) {
    errors.push("executionSemantics must remain non-executable");
  }
  if (
    typeof payload.confidenceBps !== "number" ||
    !Number.isInteger(payload.confidenceBps) ||
    payload.confidenceBps < 0 ||
    payload.confidenceBps > 10000
  ) {
    errors.push("confidenceBps must be an integer between 0 and 10000");
  }
  enumString(payload, "reviewStatus", REVIEW_STATUSES, errors);
  instant(payload.eventTime, "eventTime", errors);
  const chain = timeChain(payload, errors);
  requiredString(payload, "source", errors);
  requiredString(payload, "sourceVersion", errors);
  deletion(payload, chain.available, errors);
  return result(errors);
}

export function isKolClaimVisibleAt(input: unknown, decisionTime: string): boolean {
  const validation = validateKolClaimPayload(input);
  if (!validation.valid) return false;
  const payload = record(input);
  if (payload === null) return false;
  const errors: string[] = [];
  const available = instant(payload.availableTime, "availableTime", errors);
  const decision = instant(decisionTime, "decisionTime", errors);
  return (
    available !== undefined &&
    decision !== undefined &&
    available <= decision &&
    payload.deleted === false
  );
}

export function isKolContentVisibleAt(input: unknown, decisionTime: string): boolean {
  const validation = validateKolContentPayload(input);
  if (!validation.valid) return false;
  const payload = record(input);
  if (payload === null) return false;
  const errors: string[] = [];
  const available = instant(payload.availableTime, "availableTime", errors);
  const decision = instant(decisionTime, "decisionTime", errors);
  return (
    available !== undefined &&
    decision !== undefined &&
    available <= decision &&
    payload.deleted === false
  );
}
