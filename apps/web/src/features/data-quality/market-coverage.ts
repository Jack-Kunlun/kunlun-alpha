import { z } from "zod";
import type { MarketCoverageResponse } from "@kunlun/shared-types";

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const RFC3339_PATTERN =
  /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$/;
const DAY_MS = 86_400_000;
const NANOS_PER_MILLISECOND = 1_000_000n;
const shanghaiDateFormatter = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Shanghai",
  calendar: "gregory",
  numberingSystem: "latn",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

function legalDate(value: string): boolean {
  if (!DATE_PATTERN.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  if (
    year === undefined ||
    month === undefined ||
    day === undefined ||
    year < 1 ||
    month < 1 ||
    month > 12
  ) {
    return false;
  }
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const monthDays = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day >= 1 && day <= monthDays[month - 1]!;
}

function dateMillis(value: string): number {
  return Date.parse(`${value}T00:00:00.000Z`);
}

function inclusiveDays(dateFrom: string, dateTo: string): number {
  return (dateMillis(dateTo) - dateMillis(dateFrom)) / DAY_MS + 1;
}

function instantNanos(value: string): bigint | null {
  const match = RFC3339_PATTERN.exec(value);
  if (match === null || !legalDate(match[1]!)) return null;

  const hour = Number(match[2]);
  const minute = Number(match[3]);
  const second = Number(match[4]);
  const zone = match[6]!;
  if (hour > 23 || minute > 59 || second > 59 || zone === "-00:00") return null;

  const offsetHour = zone === "Z" ? 0 : Number(zone.slice(1, 3));
  const offsetMinute = zone === "Z" ? 0 : Number(zone.slice(4, 6));
  if (offsetHour > 23 || offsetMinute > 59) return null;

  const localMillis = Date.parse(`${match[1]}T${match[2]}:${match[3]}:${match[4]}.000Z`);
  if (!Number.isFinite(localMillis)) return null;
  const offsetMillis =
    (zone === "Z" ? 0 : (zone[0] === "+" ? 1 : -1) * (offsetHour * 60 + offsetMinute)) * 60_000;
  const fractionalNanos = BigInt((match[5] ?? "").padEnd(9, "0") || "0");
  return BigInt(localMillis - offsetMillis) * 1_000_000n + fractionalNanos;
}

function validInstant(value: string): boolean {
  return instantNanos(value) !== null;
}

function dateAtShanghai(nanos: bigint): string {
  let milliseconds = nanos / NANOS_PER_MILLISECOND;
  if (nanos < 0n && nanos % NANOS_PER_MILLISECOND !== 0n) milliseconds -= 1n;
  const parts = shanghaiDateFormatter.formatToParts(new Date(Number(milliseconds)));
  const year = parts.find((part) => part.type === "year")?.value;
  const month = parts.find((part) => part.type === "month")?.value;
  const day = parts.find((part) => part.type === "day")?.value;
  if (year === undefined || month === undefined || day === undefined) {
    throw new Error("行情覆盖响应格式无效");
  }
  return `${year.padStart(4, "0")}-${month}-${day}`;
}

const marketCoverageWindowSchema = z
  .object({
    dateFrom: z.string().refine(legalDate),
    dateTo: z.string().refine(legalDate),
    asOf: z.string().refine(validInstant),
  })
  .strict();

const marketCoverageRowSchema = z
  .object({
    unifiedCode: z.string().regex(/^\d{6}\.(SH|SZ|BJ)$/),
    source: z.enum(["tushare-pro", "akshare-tencent", "akshare-sina", "akshare-eastmoney"]),
    observedBarDays: z.number().int().min(1).max(366),
    firstDate: z.string().refine(legalDate),
    lastDate: z.string().refine(legalDate),
    latestEventTime: z.string().refine(validInstant),
    latestAvailableTime: z.string().refine(validInstant),
    latestProcessingTime: z.string().refine(validInstant),
  })
  .strict();

const marketCoverageResponseSchema = z
  .object({
    schemaVersion: z.literal("market-data-coverage-v1"),
    scope: z.literal("DAILY_RAW_SUPPORTED_SOURCES"),
    meaning: z.literal("OBSERVED_ONLY"),
    window: marketCoverageWindowSchema,
    rows: z.array(marketCoverageRowSchema).max(100),
    truncated: z.boolean(),
  })
  .strict()
  .superRefine((response, context) => {
    const { dateFrom, dateTo, asOf } = response.window;
    if (dateFrom > dateTo || inclusiveDays(dateFrom, dateTo) > 366) {
      context.addIssue({ code: "custom", path: ["window"], message: "invalid window" });
      return;
    }
    const cutoff = instantNanos(asOf);
    if (cutoff === null) return;
    const latestLogicalDate = dateAtShanghai(cutoff);
    const groups = new Set<string>();
    response.rows.forEach((row, index) => {
      if (
        row.firstDate > row.lastDate ||
        row.firstDate < dateFrom ||
        row.lastDate > dateTo ||
        row.lastDate > latestLogicalDate ||
        row.observedBarDays > inclusiveDays(row.firstDate, row.lastDate)
      ) {
        context.addIssue({ code: "custom", path: ["rows", index], message: "invalid row range" });
      }
      const groupKey = `${row.unifiedCode}\u0000${row.source}`;
      if (groups.has(groupKey)) {
        context.addIssue({ code: "custom", path: ["rows", index], message: "duplicate group" });
      }
      groups.add(groupKey);

      for (const field of [
        "latestEventTime",
        "latestAvailableTime",
        "latestProcessingTime",
      ] as const) {
        const timestamp = instantNanos(row[field]);
        if (timestamp === null || timestamp > cutoff) {
          context.addIssue({
            code: "custom",
            path: ["rows", index, field],
            message: "invalid timestamp",
          });
        }
      }
    });
  });

/** Validate an untrusted coverage response without exposing parser details. */
export function parseMarketCoverageResponse(value: unknown): MarketCoverageResponse {
  const parsed = marketCoverageResponseSchema.safeParse(value);
  if (!parsed.success) {
    throw new Error("行情覆盖响应格式无效");
  }
  return parsed.data as MarketCoverageResponse;
}
