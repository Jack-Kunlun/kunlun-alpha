import type { HotTopicSnapshot, MarketEvent } from "@kunlun/shared-types";

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
  limit: number;
}

export function validateEventQuery(value: unknown): EventQuery {
  const input = object(value, "event query");
  exactKeys(
    input,
    new Set(["dateFrom", "dateTo", "eventType", "instrumentId", "minimumConfidenceBps", "limit"]),
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
  const limit = integerString(input.limit ?? "100", "limit", 200);
  if (limit === undefined || limit < 1)
    throw new EventIntelligenceValidationError("limit must be 1 to 200");
  return {
    limit,
    ...(dateFrom === undefined ? {} : { dateFrom }),
    ...(dateTo === undefined ? {} : { dateTo }),
    ...(eventType === undefined ? {} : { eventType }),
    ...(instrumentId === undefined ? {} : { instrumentId }),
    ...(minimumConfidenceBps === undefined ? {} : { minimumConfidenceBps }),
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
  if (typeof input.asOf !== "string" || !Number.isFinite(Date.parse(input.asOf))) {
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
    asOf: new Date(input.asOf).toISOString(),
    limit,
    ...(lifecycle === undefined ? {} : { lifecycle }),
    ...(minimumScoreBps === undefined ? {} : { minimumScoreBps }),
  };
}

export function validateMarketEventPayload(value: unknown): MarketEvent {
  const input = object(value, "MarketEvent payload");
  if (
    input.schemaVersion !== "market-event-v1" ||
    typeof input.eventId !== "string" ||
    !HEX_64.test(input.eventId) ||
    typeof input.eventType !== "string" ||
    !EVENT_TYPES.has(input.eventType) ||
    typeof input.availableTime !== "string" ||
    !Number.isFinite(Date.parse(input.availableTime)) ||
    typeof input.confidenceBps !== "number" ||
    !Number.isInteger(input.confidenceBps) ||
    input.confidenceBps < 0 ||
    input.confidenceBps > 10_000 ||
    !Array.isArray(input.evidence) ||
    input.evidence.length === 0 ||
    typeof input.modelProvenance !== "object" ||
    input.modelProvenance === null
  ) {
    throw new EventIntelligenceValidationError("persisted MarketEvent payload is invalid");
  }
  return value as MarketEvent;
}

export function validateHotTopicPayload(value: unknown): HotTopicSnapshot {
  const input = object(value, "HotTopicSnapshot payload");
  if (
    input.schemaVersion !== "hot-topic-snapshot-v1" ||
    typeof input.snapshotId !== "string" ||
    !HEX_64.test(input.snapshotId) ||
    typeof input.lifecycle !== "string" ||
    !LIFECYCLES.has(input.lifecycle) ||
    typeof input.decisionTime !== "string" ||
    !Number.isFinite(Date.parse(input.decisionTime)) ||
    typeof input.scoreBps !== "number" ||
    !Number.isInteger(input.scoreBps) ||
    input.scoreBps < 0 ||
    input.scoreBps > 10_000 ||
    typeof input.confidenceBps !== "number" ||
    !Number.isInteger(input.confidenceBps)
  ) {
    throw new EventIntelligenceValidationError("persisted HotTopicSnapshot payload is invalid");
  }
  return value as HotTopicSnapshot;
}
