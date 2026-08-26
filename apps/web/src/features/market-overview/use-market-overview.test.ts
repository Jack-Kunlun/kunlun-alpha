import { describe, expect, it } from "vitest";
import {
  CURRENT_REFRESH_INTERVAL_MS,
  marketOverviewQuery,
  marketOverviewRefreshInterval,
} from "./use-market-overview";

describe("market overview request policy", () => {
  it("polls only the current view", () => {
    expect(marketOverviewQuery(null)).toBeUndefined();
    expect(marketOverviewRefreshInterval(null)).toBe(CURRENT_REFRESH_INTERVAL_MS);
  });

  it("pins historical mode to one explicit asOf without polling", () => {
    const asOf = "2026-08-25T07:00:00.000Z";
    expect(marketOverviewQuery(asOf)).toEqual({ asOf });
    expect(marketOverviewRefreshInterval(asOf)).toBe(0);
  });
});
