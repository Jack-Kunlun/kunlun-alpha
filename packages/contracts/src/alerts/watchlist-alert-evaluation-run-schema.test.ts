import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const schema = JSON.parse(
  readFileSync("schemas/alerts/watchlist-alert-evaluation-run.json", "utf8"),
) as {
  additionalProperties: boolean;
  required: string[];
  properties: Record<string, unknown>;
};

describe("watchlist alert evaluation run schema", () => {
  it("is closed and requires bounded audit counters plus the no-order meaning", () => {
    expect(schema.additionalProperties).toBe(false);
    expect(schema.required).toEqual(
      expect.arrayContaining([
        "rulesScanned",
        "evaluated",
        "skippedUnsupported",
        "skippedNoData",
        "failed",
        "dataMeaning",
      ]),
    );
    expect(schema.properties).not.toHaveProperty("order");
    expect(schema.properties).not.toHaveProperty("broker");
  });
});
