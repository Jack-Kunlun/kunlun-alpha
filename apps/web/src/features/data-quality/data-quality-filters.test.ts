import { describe, expect, it } from "vitest";
import { validateDataQualityFilters } from "./data-quality-filters";

describe("data quality filter validation", () => {
  it("trims and canonicalizes a valid security code and omits blank filters", () => {
    expect(
      validateDataQualityFilters({
        date: "2026-09-05",
        source: "",
        unifiedCode: " 600519.sh ",
        status: "",
      }),
    ).toEqual({
      ok: true,
      filters: { date: "2026-09-05", unifiedCode: "600519.SH" },
      status: undefined,
    });
    expect(
      validateDataQualityFilters({ date: "", source: "", unifiedCode: "", status: "" }),
    ).toEqual({
      ok: true,
      filters: {},
      status: undefined,
    });
  });

  it.each([
    { date: "2026-02-30", source: "", unifiedCode: "", status: "" },
    { date: "2026-09-05", source: "unknown", unifiedCode: "", status: "" },
    { date: "2026-09-05", source: "", unifiedCode: "600519", status: "" },
    { date: "2026-09-05", source: "", unifiedCode: "", status: "IGNORED" },
  ])("rejects invalid filters without producing a query", (draft) => {
    const result = validateDataQualityFilters(draft);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.filters).toBeNull();
      expect(Object.keys(result.errors)).not.toHaveLength(0);
    }
  });
});
