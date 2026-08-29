import type { InstrumentBarsResponse } from "@kunlun/shared-types";
import { apiClient } from "@/lib/api-client";
import { useApiObjectQuery } from "@/lib/use-api-query";

const INSTRUMENT = /^[0-9]{6}\.(SH|SZ|BJ)$/;
const DEFAULT_LIMIT = 250;
const MAX_LIMIT = 500;

export function instrumentBarsPath(instrumentId: string): string {
  return "/v1/instrument-intelligence/" + encodeURIComponent(instrumentId) + "/bars";
}

export function instrumentBarsQuery(
  asOf: string | null,
  limit = DEFAULT_LIMIT,
): Record<string, string> {
  const boundedLimit = Math.min(MAX_LIMIT, Math.max(1, Math.trunc(limit)));
  return asOf === null
    ? { mode: "CURRENT", limit: String(boundedLimit) }
    : { mode: "HISTORICAL", asOf, limit: String(boundedLimit) };
}

export function useInstrumentBars(instrumentId: string, asOf: string | null) {
  const enabled = INSTRUMENT.test(instrumentId);
  return useApiObjectQuery(
    () =>
      apiClient.get<InstrumentBarsResponse>(
        instrumentBarsPath(instrumentId),
        instrumentBarsQuery(asOf),
      ),
    [instrumentId, asOf],
    enabled,
    asOf === null ? 30_000 : 0,
  );
}
