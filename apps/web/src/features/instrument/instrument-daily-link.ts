import { isCanonicalInstrumentId } from "./use-instrument-intelligence";

/** Open the existing current daily-data route without carrying another page's historical filters. */
export function currentInstrumentDailyHref(instrumentId: string): string | null {
  return isCanonicalInstrumentId(instrumentId)
    ? `/instruments/${encodeURIComponent(instrumentId)}`
    : null;
}
