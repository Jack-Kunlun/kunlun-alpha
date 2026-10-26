import type { InstrumentBarsResponse } from "@kunlun/shared-types";
import { apiClient } from "@/lib/api-client";
import { useApiObjectQuery, type ObjectQueryResult } from "@/lib/use-api-query";

const INSTRUMENT = /^[0-9]{6}\.(SH|SZ|BJ)$/;
const DEFAULT_LIMIT = 250;
const MAX_LIMIT = 500;

export const INSTRUMENT_BAR_WINDOWS = [20, 60, 120, 250, 500] as const;
export type InstrumentBarWindow = (typeof INSTRUMENT_BAR_WINDOWS)[number];

interface BoundBarsResponse {
  requestKey: string;
  response: InstrumentBarsResponse;
}

export function bindInstrumentBarsResult(
  result: ObjectQueryResult<BoundBarsResponse>,
  requestKey: string,
): ObjectQueryResult<InstrumentBarsResponse> {
  if (result.data !== null && result.data.requestKey !== requestKey) {
    return { status: "loading", data: null, error: null };
  }
  return { ...result, data: result.data?.response ?? null };
}

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

export function useInstrumentBars(
  instrumentId: string,
  asOf: string | null,
  limit: InstrumentBarWindow = 250,
  refresh = true,
) {
  const enabled = INSTRUMENT.test(instrumentId);
  const requestKey = `${instrumentId}|${asOf ?? "CURRENT"}|${limit}`;
  const result = useApiObjectQuery(
    async () => ({
      requestKey,
      response: await apiClient.get<InstrumentBarsResponse>(
        instrumentBarsPath(instrumentId),
        instrumentBarsQuery(asOf, limit),
      ),
    }),
    [instrumentId, asOf, limit],
    enabled,
    asOf === null && refresh ? 30_000 : 0,
  );
  return bindInstrumentBarsResult(result, requestKey);
}
