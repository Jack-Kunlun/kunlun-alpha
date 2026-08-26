import type { InstrumentIntelligenceDetail } from "@kunlun/shared-types";
import { apiClient } from "@/lib/api-client";
import { useApiObjectQuery } from "@/lib/use-api-query";

const INSTRUMENT = /^[0-9]{6}\.(SH|SZ|BJ)$/;

export function instrumentIntelligencePath(instrumentId: string): string {
  return "/instrument-intelligence/" + encodeURIComponent(instrumentId);
}

export function instrumentIntelligenceQuery(
  asOf: string | null,
): Record<string, string> {
  return asOf === null ? { mode: "CURRENT" } : { mode: "HISTORICAL", asOf };
}

export function useInstrumentIntelligence(
  instrumentId: string,
  asOf: string | null,
) {
  const enabled = INSTRUMENT.test(instrumentId);
  return useApiObjectQuery(
    () =>
      apiClient.get<InstrumentIntelligenceDetail>(
        instrumentIntelligencePath(instrumentId),
        instrumentIntelligenceQuery(asOf),
      ),
    [instrumentId, asOf],
    enabled,
    asOf === null ? 30_000 : 0,
  );
}

export function isCanonicalInstrumentId(value: string): boolean {
  return INSTRUMENT.test(value);
}
