import type { SeatKolWorkbenchQuery } from "./seat-kol.types";

const KEYS = new Set(["asOf", "entityType", "reviewStatus", "query"]);
const ENTITY_TYPES = new Set(["ALL", "SEAT", "KOL"]);
const REVIEW_STATUSES = new Set(["ALL", "UNREVIEWED", "IN_REVIEW", "APPROVED", "REJECTED"]);
const TIMEZONE = /(Z|[+-][0-9]{2}:[0-9]{2})$/;

export class SeatKolValidationError extends Error {}

export function validateSeatKolQuery(value: unknown): SeatKolWorkbenchQuery {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new SeatKolValidationError("query must be an object");
  }
  const input = value as Record<string, unknown>;
  for (const key of Object.keys(input)) {
    if (!KEYS.has(key)) throw new SeatKolValidationError(`unknown filter: ${key}`);
  }
  if (typeof input["asOf"] !== "string" || !TIMEZONE.test(input["asOf"])) {
    throw new SeatKolValidationError("asOf must be a timezone-aware RFC3339 instant");
  }
  const parsedAsOf = new Date(input["asOf"]);
  if (Number.isNaN(parsedAsOf.getTime())) {
    throw new SeatKolValidationError("asOf must be a valid RFC3339 instant");
  }
  const entityType = input["entityType"] ?? "ALL";
  if (typeof entityType !== "string" || !ENTITY_TYPES.has(entityType)) {
    throw new SeatKolValidationError("entityType must be ALL, SEAT or KOL");
  }
  const reviewStatus = input["reviewStatus"] ?? "ALL";
  if (typeof reviewStatus !== "string" || !REVIEW_STATUSES.has(reviewStatus)) {
    throw new SeatKolValidationError("reviewStatus is invalid");
  }
  const rawQuery = input["query"];
  if (rawQuery !== undefined && (typeof rawQuery !== "string" || rawQuery.trim().length > 100)) {
    throw new SeatKolValidationError("query must be at most 100 characters");
  }
  const query = typeof rawQuery === "string" ? rawQuery.trim() : "";
  return {
    asOf: parsedAsOf.toISOString(),
    entityType: entityType as SeatKolWorkbenchQuery["entityType"],
    reviewStatus: reviewStatus as SeatKolWorkbenchQuery["reviewStatus"],
    ...(query ? { query } : {}),
  };
}
