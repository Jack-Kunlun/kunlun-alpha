import { describe, expect, it } from "vitest";

import claimSchema from "../../schemas/kol/claim.json";
import contentSchema from "../../schemas/kol/content.json";
import evidenceSchema from "../../schemas/kol/evidence.json";
import mentionSchema from "../../schemas/kol/mention.json";
import positionClaimSchema from "../../schemas/kol/position-claim.json";

type JsonObject = { [key: string]: unknown };

const schemas = [
  contentSchema,
  mentionSchema,
  evidenceSchema,
  claimSchema,
  positionClaimSchema,
] as JsonObject[];

function properties(schema: JsonObject): JsonObject {
  return schema.properties as JsonObject;
}

describe("KOL V1 schemas", () => {
  it("uses collision-free versioned public contract names", () => {
    expect(schemas.map((schema) => schema.title)).toEqual([
      "KolContent",
      "KolMention",
      "KolEvidence",
      "KolClaim",
      "KolPositionClaim",
    ]);
    for (const schema of schemas) {
      expect(schema.type).toBe("object");
      expect(schema.additionalProperties).toBe(false);
      expect((schema.required as string[]).some((field) => field === "schemaVersion")).toBe(true);
    }
  });

  it("keeps evidence bound to immutable content versions", () => {
    const evidence = properties(evidenceSchema);
    for (const field of [
      "evidenceId",
      "revisionId",
      "contentId",
      "contentVersion",
      "contentAvailableTime",
      "source",
      "sourceVersion",
      "availableTime",
      "locator",
      "excerpt",
      "evidenceGrade",
      "evidenceGradeVersion",
    ]) {
      expect(evidence[field]).toBeDefined();
    }
    expect(String(evidenceSchema.$comment)).toMatch(/immutable|contentVersion|locator/i);
    expect(evidence.locator).toMatchObject({ minLength: 1, maxLength: 2048 });
    expect(evidence.excerpt).toMatchObject({ minLength: 1, maxLength: 4000 });
    expect((evidenceSchema.definitions as JsonObject).KolEvidenceGrade).toMatchObject({
      enum: ["PRIMARY_SOURCE", "SECONDARY_SOURCE", "TERTIARY_SOURCE", "UNCLASSIFIED"],
    });
    expect((evidenceSchema.definitions as JsonObject).KolEvidenceGradeVersion).toMatchObject({
      enum: ["evidence-grade-v1"],
    });
  });

  it("requires claim evidence, canonical instruments, attribution, uncertainty and review", () => {
    const claim = properties(claimSchema);
    expect(claim.instrumentId).toMatchObject({ pattern: "^[0-9]{6}\\.(SH|SZ|BJ)$" });
    expect(claim.evidence).toMatchObject({ type: "array", minItems: 1, uniqueItems: true });
    expect(claim.confidenceBps).toMatchObject({ type: "integer", minimum: 0, maximum: 10000 });
    expect(claim.statement).toMatchObject({ minLength: 1, maxLength: 10000 });
    expect(claim.eventTime).toMatchObject({ format: "date-time" });
    expect(claim.publishTime).toMatchObject({ format: "date-time" });
    expect(claim.ingestTime).toMatchObject({ format: "date-time" });
    expect(claim.processingTime).toMatchObject({ format: "date-time" });
    expect(claim.availableTime).toMatchObject({ format: "date-time" });
    expect(String(claimSchema.$comment)).toMatch(/not.*Trade|non-executable|execution/i);
    expect(claimSchema.allOf).toHaveLength(3);
  });

  it("makes ambiguity and paraphrase explicit without turning mentions into claims", () => {
    const mention = properties(mentionSchema);
    expect(mention.mentionType).toBeDefined();
    expect(mention.surfaceText).toBeDefined();
    expect(mention.startOffset).toMatchObject({ type: "integer", minimum: 0 });
    expect(mention.endOffset).toMatchObject({ type: "integer", minimum: 1 });
    expect(String(mentionSchema.description)).toMatch(/not.*assertion|mention/i);
    expect(
      ((claimSchema.definitions as JsonObject).KolClaimStatementKind as JsonObject).enum,
    ).toEqual(expect.arrayContaining(["DIRECT", "QUOTE", "PARAPHRASE", "AMBIGUOUS"]));
  });

  it("makes position claims explicitly non-executable and keeps deletion metadata", () => {
    const position = properties(positionClaimSchema);
    const executionSemantics = (positionClaimSchema.definitions as JsonObject)
      .KolExecutionSemantics as JsonObject;
    expect(executionSemantics.enum).toEqual(["NON_EXECUTABLE_POSITION_CLAIM"]);
    expect(position.claimId).toBeDefined();
    expect(position.claimRevisionId).toBeDefined();
    expect(position.deleted).toBeDefined();
    expect(position.deletedAt).toBeDefined();
    expect(String(positionClaimSchema.$comment)).toMatch(/Trade|order|fill|broker/i);
  });

  it("expresses the tombstone conditional for every deletion-bearing KOL schema", () => {
    for (const schema of [contentSchema, claimSchema, positionClaimSchema] as JsonObject[]) {
      const deletionReason = properties(schema).deletionReason as JsonObject;
      expect(deletionReason).toMatchObject({ minLength: 1, maxLength: 1000 });
      const conditions = schema.allOf as JsonObject[];
      expect(conditions).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            if: { properties: { deleted: { const: true } } },
            then: expect.objectContaining({
              required: ["deletedAt", "deletionReason"],
            }),
            else: expect.objectContaining({
              properties: {
                deletedAt: { type: "null" },
                deletionReason: { type: "null" },
              },
            }),
          }),
        ]),
      );
    }
  });
});
