import { BadRequestException } from "@nestjs/common";
import type {
  CreateWatchlistAlertRuleInput,
  EvaluateWatchlistAlertInput,
  ToggleWatchlistAlertRuleInput,
  UpdateWatchlistAlertRuleInput,
  WatchlistAlertField,
  WatchlistAlertOperator,
} from "./watchlist-alerts.types";

const INSTRUMENT_PATTERN = /^[0-9]{6}\.(SH|SZ|BJ)$/;
const DECIMAL_PATTERN = /^-?(0|[1-9][0-9]*)(\.[0-9]{1,8})?$/;
const FEATURE_PATTERN = /^[a-z][a-z0-9_]{0,63}$/;
const HASH_PATTERN = /^[0-9a-f]{64}$/;
const FIELDS = new Set<WatchlistAlertField>([
  "LAST_PRICE",
  "CHANGE_BPS",
  "EMOTION_SCORE_BPS",
  "FEATURE_VALUE",
]);
const OPERATORS = new Set<WatchlistAlertOperator>(["GT", "GTE", "LT", "LTE", "EQ"]);

export function parseCreateRule(value: unknown): CreateWatchlistAlertRuleInput {
  const body = object(value, "request body");
  exactKeys(
    body,
    [
      "clientRequestId",
      "name",
      "enabled",
      "instrumentIds",
      "condition",
      "quietPeriod",
      "throttleSeconds",
      "notificationChannel",
    ],
    "request body",
  );
  const instrumentIds = array(body.instrumentIds, "instrumentIds").map((item, index) =>
    patternString(item, INSTRUMENT_PATTERN, `instrumentIds[${index}]`, 9),
  );
  if (instrumentIds.length === 0 || instrumentIds.length > 100) {
    invalid("instrumentIds must contain between 1 and 100 instruments");
  }
  if (new Set(instrumentIds).size !== instrumentIds.length) {
    invalid("instrumentIds must not contain duplicates");
  }

  return {
    clientRequestId: boundedString(body.clientRequestId, "clientRequestId", 1, 128),
    name: boundedString(body.name, "name", 1, 80),
    enabled: optionalBoolean(body.enabled, true, "enabled"),
    instrumentIds: instrumentIds as CreateWatchlistAlertRuleInput["instrumentIds"],
    condition: condition(body.condition),
    quietPeriod: quietPeriod(body.quietPeriod),
    throttleSeconds: optionalInteger(body.throttleSeconds, 300, 0, 86_400, "throttleSeconds"),
    notificationChannel: literal(
      body.notificationChannel ?? "IN_APP",
      "IN_APP",
      "notificationChannel",
    ),
  };
}

export function parseToggleRule(value: unknown): ToggleWatchlistAlertRuleInput {
  const body = object(value, "request body");
  exactKeys(body, ["clientRequestId", "enabled"], "request body");
  return {
    clientRequestId: boundedString(body.clientRequestId, "clientRequestId", 1, 128),
    enabled: boolean(body.enabled, "enabled"),
  };
}

export function parseUpdateRule(value: unknown): UpdateWatchlistAlertRuleInput {
  const body = object(value, "request body");
  exactKeys(body, ["clientRequestId", "expectedRevision", "name", "threshold"], "request body");
  if (!Number.isSafeInteger(body.expectedRevision) || (body.expectedRevision as number) < 1) {
    invalid("expectedRevision must be a safe positive integer");
  }
  return {
    clientRequestId: boundedString(body.clientRequestId, "clientRequestId", 1, 128),
    expectedRevision: body.expectedRevision as number,
    name: boundedString(body.name, "name", 1, 80),
    threshold: patternString(body.threshold, DECIMAL_PATTERN, "threshold", 80),
  };
}

export function parseEvaluation(value: unknown): EvaluateWatchlistAlertInput {
  const body = object(value, "request body");
  exactKeys(
    body,
    [
      "ruleId",
      "eventId",
      "instrumentId",
      "field",
      "featureName",
      "observedValue",
      "eventTime",
      "availableTime",
    ],
    "request body",
  );
  const field = enumValue(body.field, FIELDS, "field");
  const featureName = nullableFeature(body.featureName);
  if ((field === "FEATURE_VALUE") !== (featureName !== null)) {
    invalid("featureName is required only when field is FEATURE_VALUE");
  }
  const eventTime = isoTime(body.eventTime, "eventTime");
  const availableTime = isoTime(body.availableTime, "availableTime");
  if (Date.parse(eventTime) > Date.parse(availableTime)) {
    invalid("eventTime must not be later than availableTime");
  }
  return {
    ruleId: patternString(body.ruleId, HASH_PATTERN, "ruleId", 64),
    eventId: boundedString(body.eventId, "eventId", 1, 128),
    instrumentId: patternString(body.instrumentId, INSTRUMENT_PATTERN, "instrumentId", 9),
    field,
    featureName,
    observedValue: patternString(body.observedValue, DECIMAL_PATTERN, "observedValue", 80),
    eventTime,
    availableTime,
  };
}

function condition(value: unknown): CreateWatchlistAlertRuleInput["condition"] {
  const input = object(value, "condition");
  exactKeys(input, ["field", "operator", "threshold", "featureName"], "condition");
  const field = enumValue(input.field, FIELDS, "condition.field");
  const featureName = nullableFeature(input.featureName);
  if ((field === "FEATURE_VALUE") !== (featureName !== null)) {
    invalid("condition.featureName is required only when field is FEATURE_VALUE");
  }
  return {
    field,
    operator: enumValue(input.operator, OPERATORS, "condition.operator"),
    threshold: patternString(input.threshold, DECIMAL_PATTERN, "condition.threshold", 80),
    featureName,
  };
}

function quietPeriod(value: unknown): CreateWatchlistAlertRuleInput["quietPeriod"] {
  if (value === undefined || value === null) return null;
  const input = object(value, "quietPeriod");
  exactKeys(input, ["timezone", "startMinute", "endMinute"], "quietPeriod");
  const startMinute = integer(input.startMinute, 0, 1439, "quietPeriod.startMinute");
  const endMinute = integer(input.endMinute, 0, 1439, "quietPeriod.endMinute");
  if (startMinute === endMinute) invalid("quietPeriod cannot cover an ambiguous full day");
  return {
    timezone: literal(input.timezone, "Asia/Shanghai", "quietPeriod.timezone"),
    startMinute,
    endMinute,
  };
}

function nullableFeature(value: unknown): string | null {
  if (value === undefined || value === null) return null;
  return patternString(value, FEATURE_PATTERN, "featureName", 64);
}

function object(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    invalid(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function array(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) invalid(`${label} must be an array`);
  return value;
}

function exactKeys(value: Record<string, unknown>, allowed: string[], label: string): void {
  const extras = Object.keys(value).filter((key) => !allowed.includes(key));
  if (extras.length > 0) invalid(`${label} contains unsupported fields: ${extras.join(", ")}`);
}

function boundedString(value: unknown, label: string, minimum: number, maximum: number): string {
  if (typeof value !== "string") invalid(`${label} must be a string`);
  const normalized = value.trim();
  if (normalized.length < minimum || normalized.length > maximum) {
    invalid(`${label} length must be between ${minimum} and ${maximum}`);
  }
  return normalized;
}

function patternString(value: unknown, pattern: RegExp, label: string, maximum: number): string {
  const normalized = boundedString(value, label, 1, maximum);
  if (!pattern.test(normalized)) invalid(`${label} has an invalid format`);
  return normalized;
}

function boolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") invalid(`${label} must be a boolean`);
  return value;
}

function optionalBoolean(value: unknown, fallback: boolean, label: string): boolean {
  return value === undefined ? fallback : boolean(value, label);
}

function integer(value: unknown, minimum: number, maximum: number, label: string): number {
  if (!Number.isInteger(value) || (value as number) < minimum || (value as number) > maximum) {
    invalid(`${label} must be an integer between ${minimum} and ${maximum}`);
  }
  return value as number;
}

function optionalInteger(
  value: unknown,
  fallback: number,
  minimum: number,
  maximum: number,
  label: string,
): number {
  return value === undefined ? fallback : integer(value, minimum, maximum, label);
}

function enumValue<T extends string>(value: unknown, allowed: Set<T>, label: string): T {
  if (typeof value !== "string" || !allowed.has(value as T)) {
    invalid(`${label} is not supported`);
  }
  return value as T;
}

function literal<T extends string>(value: unknown, expected: T, label: string): T {
  if (value !== expected) invalid(`${label} must be ${expected}`);
  return expected;
}

function isoTime(value: unknown, label: string): string {
  const input = boundedString(value, label, 1, 64);
  const timestamp = Date.parse(input);
  if (!Number.isFinite(timestamp)) invalid(`${label} must be an ISO 8601 timestamp`);
  return new Date(timestamp).toISOString();
}

function invalid(message: string): never {
  throw new BadRequestException(message);
}
