import { describe, expect, it } from "vitest";

import aliasSchema from "../../schemas/seat/alias.json";
import performanceSchema from "../../schemas/seat/performance.json";
import preferenceSchema from "../../schemas/seat/preference.json";
import profileSchema from "../../schemas/seat/seat-profile.json";
import tradeSchema from "../../schemas/seat/trade.json";

type JsonObject = { [key: string]: unknown };

const schemas = [
  profileSchema,
  aliasSchema,
  tradeSchema,
  performanceSchema,
  preferenceSchema,
] as JsonObject[];

function properties(schema: JsonObject): JsonObject {
  return schema.properties as JsonObject;
}

function resolve(schema: JsonObject, value: JsonObject): JsonObject {
  const ref = value.$ref;
  if (typeof ref !== "string") return value;
  const name = ref.split("/").at(-1);
  return name === undefined ? value : ((schema.definitions as JsonObject)[name] as JsonObject);
}

describe("Seat V1 schemas", () => {
  it("uses collision-free public contract names", () => {
    expect(schemas.map((schema) => schema.title)).toEqual([
      "SeatProfile",
      "SeatAlias",
      "SeatTrade",
      "SeatPerformance",
      "SeatPreference",
    ]);
  });

  it("are closed, versioned root contracts", () => {
    for (const schema of schemas) {
      const required = schema.required as string[];
      expect(schema.type).toBe("object");
      expect(schema.additionalProperties).toBe(false);
      expect(required).toContain("schemaVersion");
      expect(resolve(schema, properties(schema).schemaVersion as JsonObject).type).toBe("string");
    }
  });

  it("keeps seat identity independent from mutable names", () => {
    const profile = properties(profileSchema);
    expect((profile.seatId as JsonObject).pattern).toBe("^seat-[0-9a-f]{64}$");
    expect(resolve(profileSchema, profile.seatIdAlgorithm as JsonObject).enum).toEqual([
      "seat-id-v1",
    ]);
    expect(String(profileSchema.$comment)).toContain("SHA-256");
    expect(String(profileSchema.$comment)).toContain("UTF-8");
    expect(String(profileSchema.$comment)).toContain("kunlun-seat-id-v1");
    expect((profile.identityKey as JsonObject).minLength).toBe(1);
    expect((profile.identityKey as JsonObject).pattern).toBe("^[^\\s:]+(?::[^\\s:]+)+$");
    expect((profile.canonicalName as JsonObject).type).toEqual(["string", "null"]);
    expect(resolve(profileSchema, profile.seatKind as JsonObject).enum).toEqual(
      expect.arrayContaining(["BROKER_BRANCH", "INSTITUTION", "UNKNOWN"]),
    );
  });

  it("defines half-open timezone-aware alias validity intervals", () => {
    const alias = properties(aliasSchema);
    const validFrom = alias.validFrom as JsonObject;
    const validTo = alias.validTo as JsonObject;
    expect(validFrom.format).toBe("date-time");
    expect(validTo.format).toBe("date-time");
    expect(validTo.type).toEqual(["string", "null"]);
    expect(String(validTo.description).toLowerCase()).toContain("exclusive");
  });

  it("keeps public trade amounts as exact decimal strings with revision evidence", () => {
    const trade = properties(tradeSchema);
    for (const field of ["buyAmount", "sellAmount", "netAmount"]) {
      expect((trade[field] as JsonObject).type).toBe("string");
      expect((trade[field] as JsonObject).pattern).toBeDefined();
    }
    expect(trade.rawSeatName).toMatchObject({ type: "string" });
    expect(trade.currency).toMatchObject({ enum: ["CNY"] });
    expect(trade.evidenceId).toMatchObject({ type: "string" });
    expect(trade.previousRevisionId).toMatchObject({ type: ["string", "null"] });
    expect(String(tradeSchema.$comment)).toContain("netAmount");
  });

  it("models merge and split audit links and provenance on derived contracts", () => {
    const lineage = (profileSchema.definitions as JsonObject).SeatLineage as JsonObject;
    expect(lineage.additionalProperties).toBe(false);
    expect((lineage.properties as JsonObject).predecessorSeatIds).toMatchObject({ minItems: 1 });
    expect((lineage.properties as JsonObject).successorSeatIds).toMatchObject({ minItems: 1 });
    for (const schema of [performanceSchema, preferenceSchema]) {
      const fields = properties(schema);
      expect(fields.source).toMatchObject({ type: "string" });
      expect(fields.evidenceId).toMatchObject({ type: "string" });
      expect(fields.availableTime).toMatchObject({ format: "date-time" });
    }
  });
});
