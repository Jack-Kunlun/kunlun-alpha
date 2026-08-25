import schema from "../../schemas/seat-kol/workbench-snapshot.json";
import { describe, expect, it } from "vitest";

type JsonObject = Record<string, unknown>;

describe("Seat/KOL workbench schema", () => {
  it("requires version, sample count and cutoff for every metric", () => {
    const definitions = schema.$defs as unknown as Record<string, JsonObject>;
    const required = definitions["metric"]?.["required"] as string[];
    expect(required).toEqual(
      expect.arrayContaining([
        "algorithmVersion",
        "policyVersion",
        "sampleCount",
        "dataCutoffTime",
      ]),
    );
  });

  it("keeps Claims and reviews explicitly separate from broker facts", () => {
    const definitions = schema.$defs as unknown as Record<string, JsonObject>;
    const claimProperties = definitions["claim"]?.["properties"] as Record<string, JsonObject>;
    const reviewProperties = definitions["reviewQueueItem"]?.["properties"] as Record<
      string,
      JsonObject
    >;
    expect(claimProperties["claimMeaning"]?.["const"]).toBe(
      "PUBLIC_WORDING_CLAIM_NOT_BROKER_TRADE",
    );
    expect(reviewProperties["reviewMeaning"]?.["const"]).toBe(
      "PUBLIC_WORDING_REVIEW_NOT_FACT_OR_EXECUTION",
    );
  });
});
