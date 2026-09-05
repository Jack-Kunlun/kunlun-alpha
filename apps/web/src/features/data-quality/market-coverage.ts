import { z } from "zod";
import type { MarketCoverageResponse } from "@kunlun/shared-types";

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const RFC3339_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

function rfc3339(value: string): boolean {
  return RFC3339_PATTERN.test(value) && Number.isFinite(Date.parse(value));
}

const marketCoverageWindowSchema = z
  .object({
    dateFrom: z.string().regex(DATE_PATTERN),
    dateTo: z.string().regex(DATE_PATTERN),
    asOf: z.string().refine(rfc3339),
  })
  .strict();

const marketCoverageRowSchema = z
  .object({
    unifiedCode: z.string().regex(/^\d{6}\.(SH|SZ|BJ)$/),
    source: z.enum(["tushare-pro", "akshare-tencent", "akshare-sina", "akshare-eastmoney"]),
    observedBarDays: z.number().int().min(1).max(366),
    firstDate: z.string().regex(DATE_PATTERN),
    lastDate: z.string().regex(DATE_PATTERN),
    latestEventTime: z.string().refine(rfc3339),
    latestAvailableTime: z.string().refine(rfc3339),
    latestProcessingTime: z.string().refine(rfc3339),
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
  .strict();

/** Validate an untrusted coverage response without exposing parser details. */
export function parseMarketCoverageResponse(value: unknown): MarketCoverageResponse {
  const parsed = marketCoverageResponseSchema.safeParse(value);
  if (!parsed.success) {
    throw new Error("行情覆盖响应格式无效");
  }
  return parsed.data as MarketCoverageResponse;
}
