import { describe, expect, it } from "vitest";
import { createRuleInstrument, filterAlertRules } from "./alert-rule-filters";
import type { WatchlistAlertRule } from "./use-watchlist-alerts";

const rules: (Pick<WatchlistAlertRule, "instrumentIds" | "enabled"> & { id: string })[] = [
  { id: "enabled-sh", enabled: true, instrumentIds: ["600519.SH"] },
  { id: "disabled-sz", enabled: false, instrumentIds: ["002594.SZ"] },
  { id: "multi", enabled: true, instrumentIds: ["000001.SZ", "600519.SH"] },
];

describe("alert rule filters", () => {
  it("combines instrument and enabled filters without changing the rule records", () => {
    expect(filterAlertRules(rules, "  600519.sh  ", "enabled")).toEqual([rules[0], rules[2]]);
    expect(filterAlertRules(rules, "002594", "disabled")).toEqual([rules[1]]);
    expect(filterAlertRules(rules, "002594", "enabled")).toEqual([]);
    expect(filterAlertRules(rules, "", "all")).toEqual(rules);
    expect(filterAlertRules(rules, "", "disabled")).toEqual([rules[1]]);
    expect(rules).toHaveLength(3);
    expect(rules[1]?.enabled).toBe(false);
  });

  it("preserves every matching instrument in a multi-instrument rule", () => {
    expect(filterAlertRules(rules, "000001.SZ", "all")).toEqual([rules[2]]);
    expect(filterAlertRules([], "600519", "all")).toEqual([]);
  });

  it("accepts one canonical create request and rejects ambiguous or vendor codes", () => {
    expect(createRuleInstrument(new URLSearchParams("createFor=002594.SZ"))).toBe("002594.SZ");
    expect(createRuleInstrument(new URLSearchParams("createFor=600519.sh"))).toBe("600519.SH");
    for (const search of [
      "",
      "createFor=",
      "createFor=SH600519",
      "createFor=600519.SH&createFor=000001.SZ",
      "createFor=https://example.test",
      "createFor=600519.SH%3Cscript%3E",
    ]) {
      expect(createRuleInstrument(new URLSearchParams(search))).toBeNull();
    }
  });
});
