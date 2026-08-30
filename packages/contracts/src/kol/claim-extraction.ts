/** Runtime boundaries for untrusted claim extraction and server review payloads. */

import { parseInstrumentCode } from "../instrument/code-parser.js";
import { createHash } from "node:crypto";
import type { ValidationResult } from "./validators.js";

export const CLAIM_EXTRACTION_CANDIDATE_SCHEMA_VERSION = "claim-extraction-candidate-v1" as const;
export const CLAIM_REVIEW_SUBMISSION_SCHEMA_VERSION = "claim-review-submission-v1" as const;
export const CLAIM_REVIEW_SCHEMA_VERSION = "claim-review-v1" as const;
export const CLAIM_EXTRACTION_ALGORITHM_VERSION = "kol-claim-extraction-v1" as const;
export const KOL_CLAIM_CANDIDATE_ID_ALGORITHM_VERSION = "kol-claim-candidate-id-v1" as const;
export const KOL_CLAIM_REVISION_ID_ALGORITHM_VERSION = "kol-claim-revision-id-v1" as const;
export const PUBLIC_SPEECH_CANDIDATE_NOT_FACT_OR_EXECUTION =
  "PUBLIC_SPEECH_CANDIDATE_NOT_FACT_OR_EXECUTION" as const;
export const PUBLIC_WORDING_REVIEWED_NOT_FACT_OR_EXECUTION =
  "PUBLIC_WORDING_REVIEWED_NOT_FACT_OR_EXECUTION" as const;

const HEX_64 = /^[0-9a-f]{64}$/;
const INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$/;
const EVENTS = new Set(["EXACT", "DATE_ONLY", "UNKNOWN"]);
const ATTRIBUTIONS = new Set(["SELF", "QUOTED", "REPORTED", "UNKNOWN"]);
const STATEMENT_KINDS = new Set(["DIRECT", "QUOTE", "PARAPHRASE", "AMBIGUOUS"]);
const ACTIONS = new Set(["BUY", "SELL", "HOLDING", "WATCH"]);
const POLARITIES = new Set(["AFFIRMED", "NEGATED"]);
const CONDITIONALITIES = new Set(["UNCONDITIONAL", "CONDITIONAL"]);
const GRADES = new Set(["PRIMARY_SOURCE", "SECONDARY_SOURCE", "TERTIARY_SOURCE", "UNCLASSIFIED"]);
const REVIEW_DECISIONS = new Set(["IN_REVIEW", "APPROVED", "REJECTED"]);

export class ClaimExtractionValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ClaimExtractionValidationError";
  }
}

type JsonRecord = Record<string, unknown>;

function record(value: unknown, name: string): JsonRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ClaimExtractionValidationError(`${name} must be an object`);
  }
  return value as JsonRecord;
}

function exactKeys(value: JsonRecord, allowed: ReadonlySet<string>, name: string): void {
  for (const key of Object.keys(value)) {
    if (!allowed.has(key))
      throw new ClaimExtractionValidationError(`unknown ${name} field: ${key}`);
  }
}

function requiredString(value: unknown, field: string, maximum = 256): string {
  if (typeof value !== "string" || value.length < 1 || value.length > maximum) {
    throw new ClaimExtractionValidationError(`${field} must be a bounded non-empty string`);
  }
  return value;
}

function identifier(value: unknown, field: string): string {
  const text = requiredString(value, field);
  if (!IDENTIFIER.test(text))
    throw new ClaimExtractionValidationError(`${field} is not a safe identifier`);
  return text;
}

function strictInteger(value: unknown, field: string, minimum = 0, maximum = 10_000): number {
  if (typeof value !== "number" || !Number.isInteger(value) || !Number.isFinite(value)) {
    throw new ClaimExtractionValidationError(`${field} must be a strict integer`);
  }
  if (value < minimum || value > maximum)
    throw new ClaimExtractionValidationError(`${field} is outside its allowed range`);
  return value;
}

function enumValue(value: unknown, field: string, values: ReadonlySet<string>): string {
  if (typeof value !== "string" || !values.has(value))
    throw new ClaimExtractionValidationError(`${field} has an invalid value`);
  return value;
}

interface ParsedInstant {
  readonly utc: Date;
  readonly fractionMicros: string;
}

function daysInMonth(year: number, month: number): number {
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  return [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1] ?? 0;
}

function isCalendarDate(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  return year >= 1 && month >= 1 && month <= 12 && day >= 1 && day <= daysInMonth(year, month);
}

function parseInstant(value: string): ParsedInstant | null {
  const match =
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|([+-])(\d{2}):(\d{2}))$/.exec(
      value,
    );
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  const offsetHour = Number(match[10] ?? 0);
  const offsetMinute = Number(match[11] ?? 0);
  if (
    !isCalendarDate(`${match[1]}-${match[2]}-${match[3]}`) ||
    hour > 23 ||
    minute > 59 ||
    second > 59 ||
    offsetHour > 23 ||
    offsetMinute > 59
  )
    return null;
  const offsetSign = match[8] === "Z" ? 0 : match[9] === "+" ? 1 : -1;
  const offsetMinutes = offsetSign * (offsetHour * 60 + offsetMinute);
  const utc = new Date(0);
  utc.setUTCFullYear(year, month - 1, day);
  utc.setUTCHours(hour, minute - offsetMinutes, second, 0);
  if (utc.getUTCFullYear() < 0 || utc.getUTCFullYear() > 9999) return null;
  return { utc, fractionMicros: (match[7] ?? "").padEnd(6, "0") };
}

function instant(value: unknown, field: string): string {
  if (typeof value !== "string" || !INSTANT.test(value) || parseInstant(value) === null) {
    throw new ClaimExtractionValidationError(
      `${field} must be a valid timezone-aware RFC3339 instant`,
    );
  }
  return value;
}

function nullableInstant(value: unknown, field: string): string | null {
  return value === null ? null : instant(value, field);
}

function nullableDate(value: unknown, field: string): string | null {
  if (value === null) return null;
  if (typeof value !== "string" || !DATE.test(value) || !isCalendarDate(value)) {
    throw new ClaimExtractionValidationError(`${field} must be a calendar date`);
  }
  return value;
}

function fingerprint(value: unknown, field: string): string {
  const text = requiredString(value, field, 64);
  if (!HEX_64.test(text))
    throw new ClaimExtractionValidationError(`${field} must be lowercase SHA-256`);
  return text;
}

const IDENTITY_TIME_FIELDS = new Set([
  "eventTime",
  "contentAvailableTime",
  "evidenceAvailableTime",
  "publishTime",
  "ingestTime",
  "processingTime",
  "availableTime",
  "deletedAt",
]);

function canonicalInstant(value: string): string {
  const parsed = parseInstant(value);
  if (parsed === null) return value;
  const fraction = /[1-9]/.test(parsed.fractionMicros) ? `.${parsed.fractionMicros}` : "";
  return `${parsed.utc.toISOString().slice(0, 19)}${fraction}Z`;
}

function instantEpochMicros(value: string): bigint | null {
  const parsed = parseInstant(value);
  if (parsed === null) return null;
  return BigInt(parsed.utc.getTime()) * 1000n + BigInt(parsed.fractionMicros || "0");
}

export function compareClaimExtractionInstants(left: string, right: string): number {
  const leftMicros = instantEpochMicros(left);
  const rightMicros = instantEpochMicros(right);
  if (leftMicros === null || rightMicros === null)
    throw new ClaimExtractionValidationError("instant comparison requires valid RFC3339 values");
  return leftMicros < rightMicros ? -1 : leftMicros > rightMicros ? 1 : 0;
}

function canonicalJson(value: unknown, field?: string): unknown {
  if (Array.isArray(value)) return value.map((item) => canonicalJson(item));
  if (value !== null && typeof value === "object") {
    const input = value as JsonRecord;
    return Object.fromEntries(
      Object.keys(input)
        .sort()
        .map((key) => [key, canonicalJson(input[key], key)]),
    );
  }
  return field !== undefined && IDENTITY_TIME_FIELDS.has(field) && typeof value === "string"
    ? canonicalInstant(value)
    : value;
}

function sha256(value: unknown): string {
  return createHash("sha256")
    .update(JSON.stringify(canonicalJson(value)), "utf8")
    .digest("hex");
}

/**
 * Produce the single canonical representation used for candidate persistence,
 * replay comparison, and integrity fingerprints. Equivalent RFC3339 instants
 * are normalized before object keys are serialized.
 */
export function canonicalizeClaimExtractionCandidatePayload(
  value: ClaimExtractionCandidatePayload,
): Readonly<JsonRecord> {
  return Object.freeze({
    ...record(canonicalJson(value), "claim extraction candidate"),
  });
}

export function computeClaimExtractionCandidatePayloadFingerprint(
  value: ClaimExtractionCandidatePayload,
): string {
  return sha256(value);
}

function candidateIdentityPayload(input: JsonRecord): JsonRecord {
  return {
    statement: input.statement,
    action: input.action,
    polarity: input.polarity,
    conditionality: input.conditionality,
    statementKind: input.statementKind,
    attribution: input.attribution,
    eventTimeStatus: input.eventTimeStatus,
    eventTime: input.eventTime,
    eventDate: input.eventDate,
    instrumentId: input.instrumentId,
    anchors: input.anchors,
    evidenceGrade: input.evidenceGrade,
    evidenceGradeVersion: input.evidenceGradeVersion,
  };
}

function revisionIdentityPayload(input: JsonRecord): JsonRecord {
  const revision = Object.fromEntries(
    Object.entries(input).filter(([key]) => key !== "revisionId" && key !== "previousRevisionId"),
  );
  return { candidateId: input.candidateId, revision };
}

export function computeCandidateIdFromPayload(value: unknown): string {
  const input = record(value, "candidate identity payload");
  return sha256({
    algorithmVersion: KOL_CLAIM_CANDIDATE_ID_ALGORITHM_VERSION,
    identity: candidateIdentityPayload(input),
  });
}

export function computeCandidateRevisionIdFromPayload(value: unknown): string {
  const input = record(value, "candidate revision payload");
  return sha256({
    algorithmVersion: KOL_CLAIM_REVISION_ID_ALGORITHM_VERSION,
    ...revisionIdentityPayload(input),
  });
}

function canonicalInstrument(value: unknown): string {
  const text = requiredString(value, "instrumentId", 9);
  const parsed = parseInstrumentCode(text.slice(0, 6));
  if (parsed === null || parsed.unifiedCode !== text)
    throw new ClaimExtractionValidationError("instrumentId must match the shared canonical parser");
  return text;
}

function validateAnchor(value: unknown, index: number): JsonRecord {
  const anchor = record(value, `anchors[${index}]`);
  const allowed = new Set([
    "anchorType",
    "sourceIndex",
    "contentId",
    "contentVersion",
    "contentRevisionId",
    "contentAvailableTime",
    "source",
    "sourceVersion",
    "startOffset",
    "endOffset",
    "excerpt",
    "evidenceGrade",
    "evidenceGradeVersion",
    "evidenceId",
    "evidenceRevisionId",
    "evidenceAvailableTime",
    "mediaId",
    "mediaVersion",
    "mediaManifestRevisionId",
    "segmentIndexes",
  ]);
  exactKeys(anchor, allowed, `anchor ${index}`);
  const kind = enumValue(anchor.anchorType, "anchorType", new Set(["CONTENT", "MEDIA"]));
  strictInteger(anchor.sourceIndex, "sourceIndex", 0, 100_000);
  requiredString(anchor.contentId, "contentId");
  requiredString(anchor.contentVersion, "contentVersion");
  requiredString(anchor.contentRevisionId, "contentRevisionId");
  instant(anchor.contentAvailableTime, "contentAvailableTime");
  requiredString(anchor.source, "source");
  requiredString(anchor.sourceVersion, "sourceVersion");
  const start = strictInteger(anchor.startOffset, "startOffset", 0, 10_000_000);
  const end = strictInteger(anchor.endOffset, "endOffset", 1, 10_000_000);
  if (end <= start)
    throw new ClaimExtractionValidationError("anchor endOffset must exceed startOffset");
  requiredString(anchor.excerpt, "excerpt", 10_000);
  enumValue(anchor.evidenceGrade, "evidenceGrade", GRADES);
  if (anchor.evidenceGradeVersion !== "evidence-grade-v1")
    throw new ClaimExtractionValidationError("unsupported evidenceGradeVersion");
  if (kind === "MEDIA") {
    requiredString(anchor.evidenceId, "evidenceId");
    requiredString(anchor.evidenceRevisionId, "evidenceRevisionId");
    instant(anchor.evidenceAvailableTime, "evidenceAvailableTime");
    requiredString(anchor.mediaId, "mediaId");
    requiredString(anchor.mediaVersion, "mediaVersion");
    requiredString(anchor.mediaManifestRevisionId, "mediaManifestRevisionId");
    if (
      !Array.isArray(anchor.segmentIndexes) ||
      anchor.segmentIndexes.length < 1 ||
      anchor.segmentIndexes.length > 1000
    )
      throw new ClaimExtractionValidationError("media anchor segmentIndexes must be non-empty");
    const seen = new Set<number>();
    for (const [segmentIndex, item] of anchor.segmentIndexes.entries()) {
      const parsed = strictInteger(item, `segmentIndexes[${segmentIndex}]`, 0, 100_000);
      if (seen.has(parsed))
        throw new ClaimExtractionValidationError("media anchor segmentIndexes must be unique");
      seen.add(parsed);
    }
  } else if (
    [
      "evidenceId",
      "evidenceRevisionId",
      "evidenceAvailableTime",
      "mediaId",
      "mediaVersion",
      "mediaManifestRevisionId",
      "segmentIndexes",
    ].some((field) => anchor[field] !== undefined)
  ) {
    throw new ClaimExtractionValidationError("content anchors cannot carry media provenance");
  }
  return anchor;
}

const CANDIDATE_KEYS = new Set([
  "schemaVersion",
  "candidateId",
  "revisionId",
  "previousRevisionId",
  "semanticLabel",
  "statement",
  "action",
  "polarity",
  "conditionality",
  "statementKind",
  "attribution",
  "eventTimeStatus",
  "eventTime",
  "eventDate",
  "instrumentId",
  "anchors",
  "evidenceGrade",
  "evidenceGradeVersion",
  "confidenceBps",
  "source",
  "sourceVersion",
  "algorithmVersion",
  "promptVersion",
  "modelProvider",
  "modelVersion",
  "configurationFingerprint",
  "policyFingerprint",
  "recognitionRunId",
  "publishTime",
  "ingestTime",
  "processingTime",
  "availableTime",
  "reviewStatus",
  "deleted",
  "deletedAt",
  "deletionReason",
]);

export function validateClaimExtractionCandidatePayload(value: unknown): ValidationResult {
  try {
    const input = record(value, "claim extraction candidate");
    exactKeys(input, CANDIDATE_KEYS, "candidate");
    if (input.schemaVersion !== CLAIM_EXTRACTION_CANDIDATE_SCHEMA_VERSION)
      throw new ClaimExtractionValidationError("unsupported schemaVersion");
    identifier(input.candidateId, "candidateId");
    identifier(input.revisionId, "revisionId");
    if (input.previousRevisionId !== null)
      identifier(input.previousRevisionId, "previousRevisionId");
    if (input.previousRevisionId === input.revisionId)
      throw new ClaimExtractionValidationError("revision cannot precede itself");
    if (input.semanticLabel !== PUBLIC_SPEECH_CANDIDATE_NOT_FACT_OR_EXECUTION)
      throw new ClaimExtractionValidationError("invalid semanticLabel");
    requiredString(input.statement, "statement", 10_000);
    enumValue(input.action, "action", ACTIONS);
    enumValue(input.polarity, "polarity", POLARITIES);
    enumValue(input.conditionality, "conditionality", CONDITIONALITIES);
    const kind = enumValue(input.statementKind, "statementKind", STATEMENT_KINDS);
    const attribution = enumValue(input.attribution, "attribution", ATTRIBUTIONS);
    if (kind === "QUOTE" && !["QUOTED", "REPORTED"].includes(attribution))
      throw new ClaimExtractionValidationError("QUOTE requires QUOTED or REPORTED attribution");
    if (kind === "PARAPHRASE" && attribution === "UNKNOWN")
      throw new ClaimExtractionValidationError("PARAPHRASE requires known attribution");
    if (kind === "AMBIGUOUS" && attribution === "SELF")
      throw new ClaimExtractionValidationError("AMBIGUOUS cannot be SELF attributed");
    const eventStatus = enumValue(input.eventTimeStatus, "eventTimeStatus", EVENTS);
    const event = nullableInstant(input.eventTime, "eventTime");
    const date = nullableDate(input.eventDate, "eventDate");
    if (eventStatus === "EXACT" && (event === null || date !== null))
      throw new ClaimExtractionValidationError("EXACT requires eventTime only");
    if (eventStatus === "DATE_ONLY" && (event !== null || date === null))
      throw new ClaimExtractionValidationError("DATE_ONLY requires eventDate only");
    if (eventStatus === "UNKNOWN" && (event !== null || date !== null))
      throw new ClaimExtractionValidationError("UNKNOWN cannot invent event time");
    canonicalInstrument(input.instrumentId);
    if (!Array.isArray(input.anchors) || input.anchors.length < 1 || input.anchors.length > 32)
      throw new ClaimExtractionValidationError("anchors must be non-empty and bounded");
    const anchors = input.anchors.map(validateAnchor);
    enumValue(input.evidenceGrade, "evidenceGrade", GRADES);
    if (input.evidenceGradeVersion !== "evidence-grade-v1")
      throw new ClaimExtractionValidationError("unsupported evidenceGradeVersion");
    strictInteger(input.confidenceBps, "confidenceBps");
    requiredString(input.source, "source");
    requiredString(input.sourceVersion, "sourceVersion");
    if (input.algorithmVersion !== CLAIM_EXTRACTION_ALGORITHM_VERSION)
      throw new ClaimExtractionValidationError("unsupported algorithmVersion");
    requiredString(input.promptVersion, "promptVersion");
    requiredString(input.modelProvider, "modelProvider");
    requiredString(input.modelVersion, "modelVersion");
    fingerprint(input.configurationFingerprint, "configurationFingerprint");
    fingerprint(input.policyFingerprint, "policyFingerprint");
    requiredString(input.recognitionRunId, "recognitionRunId");
    const publish = instant(input.publishTime, "publishTime");
    const ingest = instant(input.ingestTime, "ingestTime");
    const processing = instant(input.processingTime, "processingTime");
    const available = instant(input.availableTime, "availableTime");
    if (
      compareClaimExtractionInstants(publish, ingest) > 0 ||
      compareClaimExtractionInstants(ingest, processing) > 0 ||
      compareClaimExtractionInstants(processing, available) > 0
    )
      throw new ClaimExtractionValidationError("invalid processing time chain");
    for (const anchor of anchors) {
      if (compareClaimExtractionInstants(anchor.contentAvailableTime as string, available) > 0)
        throw new ClaimExtractionValidationError(
          "candidate availableTime precedes content evidence",
        );
      if (
        anchor.anchorType === "MEDIA" &&
        compareClaimExtractionInstants(anchor.evidenceAvailableTime as string, available) > 0
      )
        throw new ClaimExtractionValidationError("candidate availableTime precedes media evidence");
    }
    if (input.reviewStatus !== "UNREVIEWED")
      throw new ClaimExtractionValidationError("initial candidate must be UNREVIEWED");
    if (typeof input.deleted !== "boolean")
      throw new ClaimExtractionValidationError("deleted must be a strict boolean");
    if (input.deleted) {
      const deletedAt = instant(input.deletedAt, "deletedAt");
      requiredString(input.deletionReason, "deletionReason", 1000);
      if (compareClaimExtractionInstants(deletedAt, available) < 0)
        throw new ClaimExtractionValidationError("deletedAt must be >= availableTime");
    } else if (input.deletedAt !== null || input.deletionReason !== null)
      throw new ClaimExtractionValidationError(
        "non-deleted candidate cannot carry tombstone metadata",
      );
    if (input.candidateId !== computeCandidateIdFromPayload(input))
      throw new ClaimExtractionValidationError(
        "candidateId does not match canonical candidate identity",
      );
    if (input.revisionId !== computeCandidateRevisionIdFromPayload(input))
      throw new ClaimExtractionValidationError(
        "revisionId does not match canonical revision identity",
      );
    void publish;
    void available;
    return { valid: true, errors: [] };
  } catch (error) {
    return { valid: false, errors: [error instanceof Error ? error.message : "invalid candidate"] };
  }
}

export function parseClaimExtractionCandidatePayload(value: unknown): Readonly<JsonRecord> {
  const result = validateClaimExtractionCandidatePayload(value);
  if (!result.valid) throw new ClaimExtractionValidationError(result.errors.join("; "));
  return canonicalizeClaimExtractionCandidatePayload(record(value, "claim extraction candidate"));
}

const REVIEW_SUBMISSION_KEYS = new Set([
  "schemaVersion",
  "clientRequestId",
  "candidateId",
  "candidateRevisionId",
  "decision",
  "reason",
  "comment",
  "expectedPreviousReviewId",
]);
export function validateClaimReviewSubmissionPayload(value: unknown): ValidationResult {
  try {
    const input = record(value, "claim review submission");
    exactKeys(input, REVIEW_SUBMISSION_KEYS, "review submission");
    if (input.schemaVersion !== CLAIM_REVIEW_SUBMISSION_SCHEMA_VERSION)
      throw new ClaimExtractionValidationError("unsupported schemaVersion");
    identifier(input.clientRequestId, "clientRequestId");
    identifier(input.candidateId, "candidateId");
    identifier(input.candidateRevisionId, "candidateRevisionId");
    enumValue(input.decision, "decision", REVIEW_DECISIONS);
    requiredString(input.reason, "reason", 1000);
    if (input.comment !== undefined && input.comment !== null)
      requiredString(input.comment, "comment", 4000);
    if (input.expectedPreviousReviewId !== undefined && input.expectedPreviousReviewId !== null)
      identifier(input.expectedPreviousReviewId, "expectedPreviousReviewId");
    return { valid: true, errors: [] };
  } catch (error) {
    return {
      valid: false,
      errors: [error instanceof Error ? error.message : "invalid review submission"],
    };
  }
}
export function parseClaimReviewSubmissionPayload(value: unknown): Readonly<JsonRecord> {
  const result = validateClaimReviewSubmissionPayload(value);
  if (!result.valid) throw new ClaimExtractionValidationError(result.errors.join("; "));
  return Object.freeze({ ...record(value, "claim review submission") });
}

const REVIEW_KEYS = new Set([
  "schemaVersion",
  "reviewId",
  "candidateId",
  "candidateRevisionId",
  "decision",
  "reason",
  "comment",
  "reviewerRef",
  "createdAt",
  "availableAt",
  "submissionFingerprint",
  "previousReviewId",
  "reviewMeaning",
]);
export function validateClaimReviewPayload(value: unknown): ValidationResult {
  try {
    const input = record(value, "claim review");
    exactKeys(input, REVIEW_KEYS, "review");
    if (input.schemaVersion !== CLAIM_REVIEW_SCHEMA_VERSION)
      throw new ClaimExtractionValidationError("unsupported schemaVersion");
    identifier(input.reviewId, "reviewId");
    identifier(input.candidateId, "candidateId");
    identifier(input.candidateRevisionId, "candidateRevisionId");
    enumValue(input.decision, "decision", REVIEW_DECISIONS);
    requiredString(input.reason, "reason", 1000);
    if (input.comment !== null) requiredString(input.comment, "comment", 4000);
    requiredString(input.reviewerRef, "reviewerRef");
    const created = instant(input.createdAt, "createdAt");
    const available = instant(input.availableAt, "availableAt");
    if (compareClaimExtractionInstants(created, available) > 0)
      throw new ClaimExtractionValidationError("createdAt must be <= availableAt");
    fingerprint(input.submissionFingerprint, "submissionFingerprint");
    if (input.previousReviewId !== null) identifier(input.previousReviewId, "previousReviewId");
    if (input.reviewMeaning !== PUBLIC_WORDING_REVIEWED_NOT_FACT_OR_EXECUTION)
      throw new ClaimExtractionValidationError("invalid reviewMeaning");
    return { valid: true, errors: [] };
  } catch (error) {
    return { valid: false, errors: [error instanceof Error ? error.message : "invalid review"] };
  }
}
export function parseClaimReviewPayload(value: unknown): Readonly<JsonRecord> {
  const result = validateClaimReviewPayload(value);
  if (!result.valid) throw new ClaimExtractionValidationError(result.errors.join("; "));
  return Object.freeze({ ...record(value, "claim review") });
}

export type ClaimExtractionCandidatePayload = Readonly<JsonRecord>;
export type ClaimReviewSubmissionPayload = Readonly<JsonRecord>;
export type ClaimReviewPayload = Readonly<JsonRecord>;
