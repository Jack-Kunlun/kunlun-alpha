import type { HotTopicSnapshot, MarketEvent } from "@kunlun/shared-types";
import { isRfc3339Instant } from "../../common/rfc3339";

const HEX_64 = /^[0-9a-f]{64}$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const INSTRUMENT = /^[0-9]{6}\.(SH|SZ|BJ)$/;
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
const LIFECYCLES = new Set(["EMERGING", "RISING", "HOT", "COOLING", "DORMANT"]);
const MARKET_EVENT_KEYS = new Set([
  "schemaVersion",
  "eventId",
  "eventType",
  "headline",
  "summary",
  "occurTime",
  "publishTime",
  "availableTime",
  "instrumentIds",
  "sectorIds",
  "evidence",
  "modelProvenance",
  "confidenceBps",
]);
const EVIDENCE_KEYS = new Set([
  "evidenceId",
  "contentRecordId",
  "contentVersionId",
  "sourceId",
  "sourceVersion",
  "availableTime",
  "startOffset",
  "endOffset",
  "excerpt",
]);
const MODEL_PROVENANCE_KEYS = new Set([
  "producerType",
  "provider",
  "modelId",
  "modelVersion",
  "promptVersion",
  "outputSchemaVersion",
  "configurationFingerprint",
  "extractionRunId",
  "processingTime",
]);
const HOT_TOPIC_KEYS = new Set([
  "schemaVersion",
  "snapshotId",
  "topicId",
  "topicName",
  "lifecycle",
  "decisionTime",
  "windowStart",
  "windowEnd",
  "scoreBps",
  "confidenceBps",
  "components",
  "eventCount",
  "recentEventCount",
  "staleEventCount",
  "sourceCount",
  "instrumentCount",
  "sectorCount",
  "eventIds",
  "policyFingerprint",
  "previousSnapshotId",
  "algorithmVersion",
]);
const HOT_TOPIC_COMPONENT_KEYS = new Set([
  "evidenceQualityBps",
  "recencyBps",
  "sourceDiversityBps",
  "breadthBps",
  "momentumBps",
]);

export class EventIntelligenceValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EventIntelligenceValidationError";
  }
}

function object(value: unknown, name: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new EventIntelligenceValidationError(`${name} must be an object`);
  }
  return value as Record<string, unknown>;
}

function exactKeys(input: Record<string, unknown>, allowed: Set<string>): void {
  for (const key of Object.keys(input)) {
    if (!allowed.has(key)) throw new EventIntelligenceValidationError(`unknown filter: ${key}`);
  }
}

function closedRecord(value: unknown, allowed: Set<string>): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const input = value as Record<string, unknown>;
  return Object.keys(input).every((key) => allowed.has(key)) ? input : null;
}

function boundedString(value: unknown, minimum: number, maximum: number): value is string {
  return typeof value === "string" && value.length >= minimum && value.length <= maximum;
}

function rfc3339Instant(value: unknown): value is string {
  return isRfc3339Instant(value);
}

function integerBetween(value: unknown, minimum: number, maximum: number): value is number {
  return Number.isInteger(value) && Number(value) >= minimum && Number(value) <= maximum;
}

function uniqueStrings(value: unknown, predicate: (item: string) => boolean): value is string[] {
  return (
    Array.isArray(value) &&
    value.every((item) => typeof item === "string" && predicate(item)) &&
    new Set(value).size === value.length
  );
}

function validEvidenceReference(value: unknown, eventAvailableTime: string): boolean {
  const input = closedRecord(value, EVIDENCE_KEYS);
  return (
    input !== null &&
    boundedString(input.evidenceId, 1, Number.MAX_SAFE_INTEGER) &&
    boundedString(input.contentRecordId, 1, Number.MAX_SAFE_INTEGER) &&
    typeof input.contentVersionId === "string" &&
    HEX_64.test(input.contentVersionId) &&
    boundedString(input.sourceId, 1, Number.MAX_SAFE_INTEGER) &&
    boundedString(input.sourceVersion, 1, Number.MAX_SAFE_INTEGER) &&
    rfc3339Instant(input.availableTime) &&
    Date.parse(input.availableTime) <= Date.parse(eventAvailableTime) &&
    integerBetween(input.startOffset, 0, Number.MAX_SAFE_INTEGER) &&
    integerBetween(input.endOffset, 1, Number.MAX_SAFE_INTEGER) &&
    boundedString(input.excerpt, 1, 2000)
  );
}

function validModelProvenance(value: unknown): boolean {
  const input = closedRecord(value, MODEL_PROVENANCE_KEYS);
  return (
    input !== null &&
    (input.producerType === "MODEL" || input.producerType === "RULE") &&
    boundedString(input.provider, 1, Number.MAX_SAFE_INTEGER) &&
    boundedString(input.modelId, 1, Number.MAX_SAFE_INTEGER) &&
    boundedString(input.modelVersion, 1, Number.MAX_SAFE_INTEGER) &&
    boundedString(input.promptVersion, 1, Number.MAX_SAFE_INTEGER) &&
    input.outputSchemaVersion === "market-event-v1" &&
    typeof input.configurationFingerprint === "string" &&
    HEX_64.test(input.configurationFingerprint) &&
    boundedString(input.extractionRunId, 1, Number.MAX_SAFE_INTEGER) &&
    rfc3339Instant(input.processingTime)
  );
}

function validHotTopicComponents(value: unknown): boolean {
  const input = closedRecord(value, HOT_TOPIC_COMPONENT_KEYS);
  return (
    input !== null &&
    [...HOT_TOPIC_COMPONENT_KEYS].every((key) => integerBetween(input[key], 0, 10_000))
  );
}

function optionalString(value: unknown, name: string, pattern: RegExp): string | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "string" || !pattern.test(value)) {
    throw new EventIntelligenceValidationError(`${name} has an invalid format`);
  }
  return value;
}

function integerString(value: unknown, name: string, maximum: number): number | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "string" || !/^(0|[1-9][0-9]*)$/.test(value)) {
    throw new EventIntelligenceValidationError(`${name} must be an integer string`);
  }
  const parsed = Number(value);
  if (parsed > maximum) throw new EventIntelligenceValidationError(`${name} exceeds its maximum`);
  return parsed;
}

function optionalIsoTimestamp(value: unknown, name: string): string | undefined {
  if (value === undefined) return undefined;
  if (!rfc3339Instant(value)) {
    throw new EventIntelligenceValidationError(`${name} must be an ISO-8601 timestamp`);
  }
  return new Date(value).toISOString();
}

function optionalEventIds(value: unknown): string[] | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "string" || value === "") {
    throw new EventIntelligenceValidationError("eventIds must be a comma-separated list");
  }
  const eventIds = value.split(",");
  if (eventIds.length > 200 || eventIds.some((eventId) => !HEX_64.test(eventId))) {
    throw new EventIntelligenceValidationError("eventIds must contain 1 to 200 valid event IDs");
  }
  return [...new Set(eventIds)];
}

function legalDate(value: string): boolean {
  if (!DATE.test(value)) return false;
  const [yearText, monthText, dayText] = value.split("-");
  const parsed = new Date(Date.UTC(Number(yearText), Number(monthText) - 1, Number(dayText)));
  return parsed.toISOString().slice(0, 10) === value;
}

export interface EventQuery {
  dateFrom?: string;
  dateTo?: string;
  eventType?: string;
  instrumentId?: string;
  minimumConfidenceBps?: number;
  eventIds?: string[];
  asOf?: string;
  limit: number;
}

export function validateEventQuery(value: unknown): EventQuery {
  const input = object(value, "event query");
  exactKeys(
    input,
    new Set([
      "dateFrom",
      "dateTo",
      "eventType",
      "instrumentId",
      "minimumConfidenceBps",
      "eventIds",
      "asOf",
      "limit",
    ]),
  );
  const dateFrom = optionalString(input.dateFrom, "dateFrom", DATE);
  const dateTo = optionalString(input.dateTo, "dateTo", DATE);
  if ((dateFrom && !legalDate(dateFrom)) || (dateTo && !legalDate(dateTo))) {
    throw new EventIntelligenceValidationError("date filters must be legal YYYY-MM-DD dates");
  }
  if (dateFrom && dateTo && dateFrom > dateTo) {
    throw new EventIntelligenceValidationError("dateFrom must be <= dateTo");
  }
  const eventType = optionalString(input.eventType, "eventType", /^[A-Z_]+$/);
  if (eventType && !EVENT_TYPES.has(eventType)) {
    throw new EventIntelligenceValidationError("eventType is unsupported");
  }
  const instrumentId = optionalString(input.instrumentId, "instrumentId", INSTRUMENT);
  const minimumConfidenceBps = integerString(
    input.minimumConfidenceBps,
    "minimumConfidenceBps",
    10_000,
  );
  const eventIds = optionalEventIds(input.eventIds);
  const asOf = optionalIsoTimestamp(input.asOf, "asOf");
  const limit = integerString(
    input.limit ?? (eventIds === undefined ? "100" : String(eventIds.length)),
    "limit",
    200,
  );
  if (limit === undefined || limit < 1)
    throw new EventIntelligenceValidationError("limit must be 1 to 200");
  if (eventIds !== undefined && limit < eventIds.length) {
    throw new EventIntelligenceValidationError("limit must cover every requested eventId");
  }
  return {
    limit,
    ...(dateFrom === undefined ? {} : { dateFrom }),
    ...(dateTo === undefined ? {} : { dateTo }),
    ...(eventType === undefined ? {} : { eventType }),
    ...(instrumentId === undefined ? {} : { instrumentId }),
    ...(minimumConfidenceBps === undefined ? {} : { minimumConfidenceBps }),
    ...(eventIds === undefined ? {} : { eventIds }),
    ...(asOf === undefined ? {} : { asOf }),
  };
}

export interface HotTopicQuery {
  asOf: string;
  lifecycle?: string;
  minimumScoreBps?: number;
  limit: number;
}

export function validateHotTopicQuery(value: unknown): HotTopicQuery {
  const input = object(value, "hot topic query");
  exactKeys(input, new Set(["asOf", "lifecycle", "minimumScoreBps", "limit"]));
  const asOf = optionalIsoTimestamp(input.asOf, "asOf");
  if (asOf === undefined) {
    throw new EventIntelligenceValidationError("asOf must be an ISO-8601 timestamp");
  }
  const lifecycle = optionalString(input.lifecycle, "lifecycle", /^[A-Z_]+$/);
  if (lifecycle && !LIFECYCLES.has(lifecycle)) {
    throw new EventIntelligenceValidationError("lifecycle is unsupported");
  }
  const minimumScoreBps = integerString(input.minimumScoreBps, "minimumScoreBps", 10_000);
  const limit = integerString(input.limit ?? "50", "limit", 100);
  if (limit === undefined || limit < 1)
    throw new EventIntelligenceValidationError("limit must be 1 to 100");
  return {
    asOf,
    limit,
    ...(lifecycle === undefined ? {} : { lifecycle }),
    ...(minimumScoreBps === undefined ? {} : { minimumScoreBps }),
  };
}

export function validateMarketEventPayload(value: unknown): MarketEvent {
  const input = closedRecord(value, MARKET_EVENT_KEYS);
  const availableTime =
    input !== null && rfc3339Instant(input.availableTime) ? input.availableTime : null;
  if (
    input === null ||
    input.schemaVersion !== "market-event-v1" ||
    typeof input.eventId !== "string" ||
    !HEX_64.test(input.eventId) ||
    typeof input.eventType !== "string" ||
    !EVENT_TYPES.has(input.eventType) ||
    !boundedString(input.headline, 1, 500) ||
    !boundedString(input.summary, 1, 5000) ||
    !rfc3339Instant(input.occurTime) ||
    !rfc3339Instant(input.publishTime) ||
    availableTime === null ||
    !uniqueStrings(input.instrumentIds, (item) => INSTRUMENT.test(item)) ||
    !uniqueStrings(input.sectorIds, (item) => item.length > 0) ||
    !Array.isArray(input.evidence) ||
    input.evidence.length === 0 ||
    !input.evidence.every((item) => validEvidenceReference(item, availableTime ?? "")) ||
    !validModelProvenance(input.modelProvenance) ||
    !integerBetween(input.confidenceBps, 0, 10_000)
  ) {
    throw new EventIntelligenceValidationError("persisted MarketEvent payload is invalid");
  }
  return value as MarketEvent;
}

export function validateHotTopicPayload(value: unknown): HotTopicSnapshot {
  const input = closedRecord(value, HOT_TOPIC_KEYS);
  if (
    input === null ||
    input.schemaVersion !== "hot-topic-snapshot-v1" ||
    typeof input.snapshotId !== "string" ||
    !HEX_64.test(input.snapshotId) ||
    typeof input.lifecycle !== "string" ||
    !LIFECYCLES.has(input.lifecycle) ||
    !boundedString(input.topicId, 1, 128) ||
    !boundedString(input.topicName, 1, 200) ||
    !rfc3339Instant(input.decisionTime) ||
    !rfc3339Instant(input.windowStart) ||
    !rfc3339Instant(input.windowEnd) ||
    Date.parse(input.windowStart) > Date.parse(input.windowEnd) ||
    Date.parse(input.windowEnd) > Date.parse(input.decisionTime) ||
    !integerBetween(input.scoreBps, 0, 10_000) ||
    !integerBetween(input.confidenceBps, 0, 10_000) ||
    !validHotTopicComponents(input.components) ||
    !integerBetween(input.eventCount, 0, Number.MAX_SAFE_INTEGER) ||
    !integerBetween(input.recentEventCount, 0, Number.MAX_SAFE_INTEGER) ||
    !integerBetween(input.staleEventCount, 0, Number.MAX_SAFE_INTEGER) ||
    !integerBetween(input.sourceCount, 0, Number.MAX_SAFE_INTEGER) ||
    !integerBetween(input.instrumentCount, 0, Number.MAX_SAFE_INTEGER) ||
    !integerBetween(input.sectorCount, 0, Number.MAX_SAFE_INTEGER) ||
    !uniqueStrings(input.eventIds, (item) => HEX_64.test(item)) ||
    typeof input.policyFingerprint !== "string" ||
    !HEX_64.test(input.policyFingerprint) ||
    !(
      input.previousSnapshotId === undefined ||
      input.previousSnapshotId === null ||
      (typeof input.previousSnapshotId === "string" && HEX_64.test(input.previousSnapshotId))
    ) ||
    input.algorithmVersion !== "hot-score-v1"
  ) {
    throw new EventIntelligenceValidationError("persisted HotTopicSnapshot payload is invalid");
  }
  return value as HotTopicSnapshot;
}
