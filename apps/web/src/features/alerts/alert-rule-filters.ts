import { isCanonicalInstrumentId } from "../instrument/use-instrument-intelligence";
import type { WatchlistAlertRule } from "./use-watchlist-alerts";

export type RuleEnabledFilter = "all" | "enabled" | "disabled";

export function filterAlertRules<T extends Pick<WatchlistAlertRule, "instrumentIds" | "enabled">>(
  rules: readonly T[],
  instrumentQuery: string,
  enabled: RuleEnabledFilter,
): T[] {
  const query = instrumentQuery.trim().toUpperCase();
  return rules.filter(
    (rule) =>
      (enabled === "all" || rule.enabled === (enabled === "enabled")) &&
      (query === "" || rule.instrumentIds.some((id) => id.includes(query))),
  );
}

export function createRuleInstrument(params: URLSearchParams): string | null {
  const values = params.getAll("createFor");
  if (values.length !== 1) return null;
  const instrumentId = values[0]?.trim().toUpperCase() ?? "";
  return isCanonicalInstrumentId(instrumentId) ? instrumentId : null;
}
