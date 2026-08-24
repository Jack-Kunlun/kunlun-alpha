import type { EmotionReplayQuery } from "./emotion-repository";

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const VERSION_PATTERN = /^[A-Za-z0-9._-]{1,64}$/;
const SECTOR_PATTERN = /^[A-Za-z0-9._:-]{1,96}$/;
const ALLOWED_KEYS = new Set(["date", "algorithmVersion", "sectorId"]);

export class EmotionValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EmotionValidationError";
  }
}

function legalDate(value: string): boolean {
  if (!DATE_PATTERN.test(value)) return false;
  const [yearText, monthText, dayText] = value.split("-");
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return (
    parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    parsed.getUTCDate() === day
  );
}

function optionalString(value: unknown, field: string, pattern: RegExp): string | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "string" || !pattern.test(value)) {
    throw new EmotionValidationError(field + " has an invalid format");
  }
  return value;
}

export function validateEmotionQuery(input: unknown): EmotionReplayQuery {
  if (typeof input !== "object" || input === null || Array.isArray(input)) {
    throw new EmotionValidationError("query must be an object");
  }
  const record = input as Record<string, unknown>;
  for (const key of Object.keys(record)) {
    if (!ALLOWED_KEYS.has(key)) {
      throw new EmotionValidationError("unknown filter: " + key);
    }
  }
  if (typeof record.date !== "string" || !legalDate(record.date)) {
    throw new EmotionValidationError("date must be a valid YYYY-MM-DD trading date");
  }
  const query: EmotionReplayQuery = { date: record.date };
  const algorithmVersion = optionalString(
    record.algorithmVersion,
    "algorithmVersion",
    VERSION_PATTERN,
  );
  const sectorId = optionalString(record.sectorId, "sectorId", SECTOR_PATTERN);
  if (algorithmVersion !== undefined) query.algorithmVersion = algorithmVersion;
  if (sectorId !== undefined) query.sectorId = sectorId;
  return query;
}
