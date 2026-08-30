import type { EventFeedback, EventFeedbackSubmission } from "@kunlun/shared-types";

const HEX_64 = /^[0-9a-f]{64}$/;
const REFERENCE = /^[A-Za-z0-9._:-]{1,128}$/;
const INSTRUMENT = /^[0-9]{6}\.(SH|SZ|BJ)$/;
const ACTIONS = new Set(["CONFIRM", "REJECT", "CORRECT"]);
const REASONS = new Set([
  "ACCURATE",
  "WRONG_TYPE",
  "WRONG_ENTITY",
  "WRONG_EVIDENCE",
  "DUPLICATE",
  "NOT_MARKET_EVENT",
  "OTHER",
]);
const EVENT_TYPES = new Set([
  "CORPORATE",
  "EARNINGS",
  "FINANCING",
  "REGULATORY",
  "POLICY",
  "MACRO",
  "INDUSTRY",
  "MARKET",
  "RISK",
  "OTHER",
]);
const SUBMISSION_KEYS = new Set([
  "schemaVersion",
  "clientRequestId",
  "eventId",
  "modelConfigurationFingerprint",
  "action",
  "reasonCode",
  "correction",
  "comment",
]);
const CORRECTION_KEYS = new Set([
  "eventType",
  "headline",
  "summary",
  "instrumentIds",
  "sectorIds",
  "evidenceIds",
]);

export class EventFeedbackValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EventFeedbackValidationError";
  }
}

function record(value: unknown, name: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new EventFeedbackValidationError(`${name} must be an object`);
  }
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, allowed: Set<string>, name: string): void {
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) throw new EventFeedbackValidationError(`unknown ${name} field: ${key}`);
  }
}

function requiredString(value: unknown, field: string, pattern?: RegExp, maximum = 128): string {
  if (typeof value !== "string" || value.length < 1 || value.length > maximum) {
    throw new EventFeedbackValidationError(`${field} has an invalid format`);
  }
  if (pattern && !pattern.test(value)) {
    throw new EventFeedbackValidationError(`${field} has an invalid format`);
  }
  return value;
}

function stringArray(value: unknown, field: string, pattern?: RegExp): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new EventFeedbackValidationError(`${field} must be a string array`);
  }
  const result = value as string[];
  if (
    new Set(result).size !== result.length ||
    result.some((item) => !item || (pattern && !pattern.test(item)))
  ) {
    throw new EventFeedbackValidationError(`${field} contains invalid or duplicate values`);
  }
  return [...result].sort();
}

function correction(value: unknown): NonNullable<EventFeedbackSubmission["correction"]> {
  const input = record(value, "correction");
  exactKeys(input, CORRECTION_KEYS, "correction");
  if (Object.keys(input).length === 0) {
    throw new EventFeedbackValidationError("correction must contain at least one field");
  }
  const output: NonNullable<EventFeedbackSubmission["correction"]> = {};
  if (input.eventType !== undefined) {
    if (typeof input.eventType !== "string" || !EVENT_TYPES.has(input.eventType)) {
      throw new EventFeedbackValidationError("eventType is invalid");
    }
    output.eventType = input.eventType as NonNullable<
      EventFeedbackSubmission["correction"]
    >["eventType"];
  }
  if (input.headline !== undefined)
    output.headline = requiredString(input.headline, "headline", undefined, 500);
  if (input.summary !== undefined)
    output.summary = requiredString(input.summary, "summary", undefined, 5000);
  if (input.instrumentIds !== undefined)
    output.instrumentIds = stringArray(input.instrumentIds, "instrumentIds", INSTRUMENT);
  if (input.sectorIds !== undefined) output.sectorIds = stringArray(input.sectorIds, "sectorIds");
  if (input.evidenceIds !== undefined)
    output.evidenceIds = stringArray(input.evidenceIds, "evidenceIds", HEX_64);
  return output;
}

export function validateFeedbackSubmission(value: unknown): EventFeedbackSubmission {
  const input = record(value, "feedback");
  exactKeys(input, SUBMISSION_KEYS, "feedback");
  if (input.schemaVersion !== "event-feedback-submission-v1") {
    throw new EventFeedbackValidationError("unsupported feedback submission version");
  }
  if (typeof input.action !== "string" || !ACTIONS.has(input.action)) {
    throw new EventFeedbackValidationError("action is invalid");
  }
  if (typeof input.reasonCode !== "string" || !REASONS.has(input.reasonCode)) {
    throw new EventFeedbackValidationError("reasonCode is invalid");
  }
  const parsedCorrection =
    input.correction === undefined ? undefined : correction(input.correction);
  if ((input.action === "CORRECT") !== (parsedCorrection !== undefined)) {
    throw new EventFeedbackValidationError("only CORRECT feedback requires correction");
  }
  const comment =
    input.comment === undefined
      ? undefined
      : requiredString(input.comment, "comment", undefined, 1000);
  return {
    schemaVersion: "event-feedback-submission-v1",
    clientRequestId: requiredString(input.clientRequestId, "clientRequestId", REFERENCE),
    eventId: requiredString(input.eventId, "eventId", HEX_64, 64),
    modelConfigurationFingerprint: requiredString(
      input.modelConfigurationFingerprint,
      "modelConfigurationFingerprint",
      HEX_64,
      64,
    ),
    action: input.action as EventFeedbackSubmission["action"],
    reasonCode: input.reasonCode as EventFeedbackSubmission["reasonCode"],
    ...(parsedCorrection === undefined ? {} : { correction: parsedCorrection }),
    ...(comment === undefined ? {} : { comment }),
  };
}

export interface EventFeedbackQuery {
  eventId?: string;
  modelConfigurationFingerprint?: string;
  limit: number;
}

export function validateFeedbackQuery(value: unknown): EventFeedbackQuery {
  const input = record(value, "query");
  const allowed = new Set(["eventId", "modelConfigurationFingerprint", "limit"]);
  exactKeys(input, allowed, "query");
  const limitValue = input.limit ?? "100";
  if (typeof limitValue !== "string" || !/^[1-9][0-9]{0,2}$/.test(limitValue)) {
    throw new EventFeedbackValidationError("limit must be an integer string from 1 to 200");
  }
  const limit = Number(limitValue);
  if (limit > 200)
    throw new EventFeedbackValidationError("limit must be an integer string from 1 to 200");
  const eventId =
    input.eventId === undefined ? undefined : requiredString(input.eventId, "eventId", HEX_64, 64);
  const fingerprint =
    input.modelConfigurationFingerprint === undefined
      ? undefined
      : requiredString(
          input.modelConfigurationFingerprint,
          "modelConfigurationFingerprint",
          HEX_64,
          64,
        );
  return {
    limit,
    ...(eventId === undefined ? {} : { eventId }),
    ...(fingerprint === undefined ? {} : { modelConfigurationFingerprint: fingerprint }),
  };
}

export function validateReviewerRef(value: unknown): string {
  return requiredString(value, "reviewerRef", REFERENCE);
}

export function validateFeedbackRecord(value: unknown): EventFeedback {
  const input = record(value, "persisted feedback");
  const submission = validateFeedbackSubmission({
    schemaVersion: "event-feedback-submission-v1",
    clientRequestId: input.clientRequestId,
    eventId: input.eventId,
    modelConfigurationFingerprint: input.modelConfigurationFingerprint,
    action: input.action,
    reasonCode: input.reasonCode,
    ...(input.correction === undefined ? {} : { correction: input.correction }),
    ...(input.comment === undefined ? {} : { comment: input.comment }),
  });
  const createdAt = requiredString(input.createdAt, "createdAt", undefined, 64);
  const availableAt = requiredString(input.availableAt, "availableAt", undefined, 64);
  if (!Number.isFinite(Date.parse(createdAt)) || !Number.isFinite(Date.parse(availableAt))) {
    throw new EventFeedbackValidationError("feedback timestamps must be ISO-8601");
  }
  return {
    schemaVersion: "event-feedback-v1",
    feedbackId: requiredString(input.feedbackId, "feedbackId", HEX_64, 64),
    clientRequestId: submission.clientRequestId,
    eventId: submission.eventId,
    modelConfigurationFingerprint: submission.modelConfigurationFingerprint,
    action: submission.action,
    reasonCode: submission.reasonCode,
    ...(submission.correction === undefined ? {} : { correction: submission.correction }),
    ...(submission.comment === undefined ? {} : { comment: submission.comment }),
    reviewerRef: validateReviewerRef(input.reviewerRef),
    submissionFingerprint: requiredString(
      input.submissionFingerprint,
      "submissionFingerprint",
      HEX_64,
      64,
    ),
    createdAt,
    availableAt,
  };
}
