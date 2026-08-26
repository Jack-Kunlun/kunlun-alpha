const RFC3339_WITH_ZONE =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|([+-])(\d{2}):(\d{2}))$/;

export class DashboardValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DashboardValidationError";
  }
}

export interface MarketOverviewQuery {
  asOf: string;
  mode: "CURRENT" | "HISTORICAL";
}

function canonicalTimestamp(raw: string): string | null {
  const match = RFC3339_WITH_ZONE.exec(raw);
  if (match === null) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  const fraction = match[7] ?? "";
  const offsetSign = match[9];
  const offsetHour = Number(match[10] ?? 0);
  const offsetMinute = Number(match[11] ?? 0);
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (
    year === 0 ||
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > (daysInMonth[month - 1] ?? 0) ||
    hour > 23 ||
    minute > 59 ||
    second > 59 ||
    offsetHour > 23 ||
    offsetMinute > 59
  ) {
    return null;
  }
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  date.setUTCHours(hour, minute, second, Number(`${fraction}000`.slice(0, 3)));
  const unsignedOffsetMinutes = offsetHour * 60 + offsetMinute;
  const offsetMinutes = offsetSign === "+" ? unsignedOffsetMinutes : -unsignedOffsetMinutes;
  const timestamp = date.getTime() - offsetMinutes * 60_000;
  return Number.isFinite(timestamp) ? new Date(timestamp).toISOString() : null;
}

export function validateMarketOverviewQuery(input: unknown, now = new Date()): MarketOverviewQuery {
  if (typeof input !== "object" || input === null || Array.isArray(input)) {
    throw new DashboardValidationError("market overview query must be an object");
  }
  const record = input as Record<string, unknown>;
  const unknown = Object.keys(record).filter((key) => key !== "asOf");
  if (unknown.length > 0) {
    throw new DashboardValidationError(`unknown market overview query field: ${unknown[0]}`);
  }
  if (record.asOf === undefined) {
    return { asOf: now.toISOString(), mode: "CURRENT" };
  }
  if (typeof record.asOf !== "string") {
    throw new DashboardValidationError("asOf must be a timezone-aware RFC3339 string");
  }
  const asOf = canonicalTimestamp(record.asOf);
  if (asOf === null) {
    throw new DashboardValidationError("asOf must be a valid timezone-aware RFC3339 instant");
  }
  if (Date.parse(asOf) > now.getTime()) {
    throw new DashboardValidationError("asOf must not be in the future");
  }
  return { asOf, mode: "HISTORICAL" };
}
