import { describe, expect, it } from "vitest";

import marketEventSchema from "../../schemas/event/market-event.json";

type JsonObject = { [key: string]: unknown };

const schema = marketEventSchema as unknown as JsonObject & {
  required?: string[];
  additionalProperties?: boolean;
  properties?: JsonObject;
  definitions?: JsonObject;
};

describe("MarketEvent V1 schema", () => {
  it("is closed and requires every provenance boundary", () => {
    expect(schema.additionalProperties).toBe(false);
    expect(schema.required).toEqual(
      expect.arrayContaining([
        "schemaVersion",
        "eventId",
        "eventType",
        "occurTime",
        "publishTime",
        "availableTime",
        "instrumentIds",
        "sectorIds",
        "evidence",
        "modelProvenance",
        "confidenceBps",
      ]),
    );
  });

  it("requires at least one evidence reference", () => {
    const evidence = schema.properties?.["evidence"] as JsonObject;
    expect(evidence["minItems"]).toBe(1);
  });

  it("keeps evidence and model provenance objects closed", () => {
    const evidence = schema.definitions?.["EvidenceReference"] as JsonObject;
    const model = schema.definitions?.["ModelProvenance"] as JsonObject;
    expect(evidence["additionalProperties"]).toBe(false);
    expect(model["additionalProperties"]).toBe(false);
  });

  it("uses canonical securities and integer confidence", () => {
    const instruments = schema.properties?.["instrumentIds"] as JsonObject;
    const item = instruments["items"] as JsonObject;
    const confidence = schema.properties?.["confidenceBps"] as JsonObject;
    expect(item["pattern"]).toBe("^[0-9]{6}\\.(SH|SZ|BJ)$");
    expect(confidence["type"]).toBe("integer");
    expect(confidence["minimum"]).toBe(0);
    expect(confidence["maximum"]).toBe(10000);
  });
});
