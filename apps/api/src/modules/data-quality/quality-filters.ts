/**
 * Strict validation for data-quality query filters and evidence ids.
 *
 * Rejects the legacy prefix form (SH.600519), path traversal, malformed or
 * illegal dates, unknown filter keys, and oversized values before any query
 * reaches the repository.
 */

import type { QualityQuery } from "./quality-repository";

const UNIFIED_CODE_PATTERN = /^\d{6}\.(SH|SZ|BJ)$/;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const SOURCE_PATTERN = /^[A-Za-z0-9._-]{1,64}$/;
const KIND_PATTERN = /^[A-Z_][A-Z0-9_]{0,63}$/;
const EVIDENCE_ID_PATTERN = /^[a-z0-9-]{1,128}$/;

const ALLOWED_KEYS = new Set(["date", "dateFrom", "dateTo", "source", "unifiedCode", "kind"]);

export class QualityValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "QualityValidationError";
  }
}

function isLegalDate(value: string): boolean {
  if (!DATE_PATTERN.test(value)) return false;
  const parts = value.split("-");
  const year = Number(parts[0]);
  const month = Number(parts[1]);
  const day = Number(parts[2]);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

function asNonEmptyString(value: unknown, field: string): string {
  if (typeof value !== "string" || value.trim() === "") {
    throw new QualityValidationError(`${field} must be a non-empty string`);
  }
  return value;
}

function validateDate(value: unknown, field: string): string {
  const text = asNonEmptyString(value, field);
  if (!isLegalDate(text)) {
    throw new QualityValidationError(`${field} must be a valid YYYY-MM-DD date`);
  }
  return text;
}

function validateSource(value: unknown): string {
  const text = asNonEmptyString(value, "source");
  if (!SOURCE_PATTERN.test(text)) {
    throw new QualityValidationError("source contains unsupported characters");
  }
  return text;
}

function validateUnifiedCode(value: unknown): string {
  const text = asNonEmptyString(value, "unifiedCode");
  if (!UNIFIED_CODE_PATTERN.test(text)) {
    throw new QualityValidationError(
      "unifiedCode must be suffix-form like 600519.SH (legacy prefix form rejected)",
    );
  }
  return text;
}

function validateKind(value: unknown): string {
  const text = asNonEmptyString(value, "kind");
  if (!KIND_PATTERN.test(text)) {
    throw new QualityValidationError("kind must be an uppercase ASCII identifier");
  }
  return text;
}

/** Validate and normalize a raw query object into a clean QualityQuery. */
export function validateQualityQuery(input: unknown): QualityQuery {
  if (typeof input !== "object" || input === null || Array.isArray(input)) {
    throw new QualityValidationError("query must be an object");
  }
  const record = input as Record<string, unknown>;
  for (const key of Object.keys(record)) {
    if (!ALLOWED_KEYS.has(key)) {
      throw new QualityValidationError(`unknown filter: ${key}`);
    }
  }

  const filters: QualityQuery = {};
  if (record.date !== undefined) filters.date = validateDate(record.date, "date");
  if (record.dateFrom !== undefined) filters.dateFrom = validateDate(record.dateFrom, "dateFrom");
  if (record.dateTo !== undefined) filters.dateTo = validateDate(record.dateTo, "dateTo");
  if (filters.dateFrom !== undefined && filters.dateTo !== undefined && filters.dateFrom > filters.dateTo) {
    throw new QualityValidationError("dateFrom must not be after dateTo");
  }
  if (record.source !== undefined) filters.source = validateSource(record.source);
  if (record.unifiedCode !== undefined) filters.unifiedCode = validateUnifiedCode(record.unifiedCode);
  if (record.kind !== undefined) filters.kind = validateKind(record.kind);
  return filters;
}

/** Validate a safe internal evidence/event id before it is looked up. */
export function validateEvidenceId(value: unknown): string {
  const text = asNonEmptyString(value, "id");
  if (!EVIDENCE_ID_PATTERN.test(text)) {
    throw new QualityValidationError("invalid evidence id");
  }
  return text;
}
