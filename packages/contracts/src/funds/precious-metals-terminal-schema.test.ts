import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const schema = JSON.parse(
  readFileSync("schemas/funds/precious-metals-terminal.json", "utf8"),
) as Record<string, unknown>;

describe("precious-metals terminal contract", () => {
  it("keeps the terminal read-only and NAV/iNAV explicitly non-executable", () => {
    expect(schema["title"]).toBe("PreciousMetalsTerminalSnapshot");
    expect(JSON.stringify(schema)).toContain("NAV_INAV_NON_EXECUTABLE");
    expect(JSON.stringify(schema)).toContain("REFERENCE_ONLY");
    expect(JSON.stringify(schema)).not.toMatch(/P6-N|Phase 6/);
  });

  it("requires point-in-time, gap, provenance, ranking and event fields", () => {
    expect(schema["required"]).toEqual(
      expect.arrayContaining([
        "effectiveAsOf",
        "status",
        "gaps",
        "sourceVersions",
        "evidenceIds",
        "funds",
        "events",
      ]),
    );
    expect(JSON.stringify(schema)).toContain("premiumDiscountBps");
    expect(JSON.stringify(schema)).toContain("LATEST_EXCHANGE_TURNOVER_CNY");
  });
});
