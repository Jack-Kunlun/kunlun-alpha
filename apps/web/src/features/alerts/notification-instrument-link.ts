import { isCanonicalInstrumentId } from "@/features/instrument/use-instrument-intelligence";

/** Recent notifications open current research, independent of another page's historical filters. */
export function notificationInstrumentHref(instrumentId: string): string | null {
  return isCanonicalInstrumentId(instrumentId)
    ? `/instruments/${encodeURIComponent(instrumentId)}`
    : null;
}
