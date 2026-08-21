import { describe, expect, it } from "vitest";

import rawContentSchema from "../../schemas/content/raw-content.json";

type JsonObject = { [key: string]: unknown };
type IfClause = { if?: JsonObject; then?: JsonObject };

const schema = rawContentSchema as unknown as JsonObject & {
  required?: string[];
  additionalProperties?: boolean;
  allOf?: IfClause[];
};

/**
 * Minimal Draft-07 conditional check for the keywords this schema actually
 * uses: root-level `required`, and `allOf` clauses with `if` (required +
 * properties.const) and `then` (required + properties.type).
 */
function matchesIf(ifSchema: JsonObject, payload: JsonObject): boolean {
  const required = ifSchema["required"];
  if (Array.isArray(required)) {
    for (const field of required) {
      if (!(field in payload)) return false;
    }
  }
  const properties = ifSchema["properties"];
  if (properties && typeof properties === "object") {
    for (const [field, sub] of Object.entries(properties)) {
      if (sub && typeof sub === "object" && "const" in sub) {
        if (payload[field] !== (sub as { const: unknown }).const) return false;
      }
    }
  }
  return true;
}

function validate(payload: JsonObject): string[] {
  const errors: string[] = [];
  for (const field of schema.required ?? []) {
    if (!(field in payload)) errors.push(`missing required field: ${field}`);
  }
  for (const clause of schema.allOf ?? []) {
    const ifSchema = clause.if;
    const thenSchema = clause.then;
    if (!ifSchema || !thenSchema || !matchesIf(ifSchema, payload)) continue;
    const thenRequired = thenSchema["required"];
    if (Array.isArray(thenRequired)) {
      for (const field of thenRequired) {
        if (!(field in payload) || payload[field] === null) {
          errors.push(`then required field: ${field}`);
        }
      }
    }
    const deletedAtType = (thenSchema["properties"] as JsonObject | undefined)?.[
      "deletedAt"
    ] as { type?: string } | undefined;
    if (deletedAtType?.type === "null" && payload["deletedAt"] !== null && payload["deletedAt"] !== undefined) {
      errors.push("deletedAt must be null when deleted is false");
    }
    if (
      deletedAtType?.type === "string" &&
      payload["deletedAt"] !== undefined &&
      typeof payload["deletedAt"] !== "string"
    ) {
      errors.push("deletedAt must be a date-time string when deleted is true");
    }
  }
  return errors;
}

describe("RawContent schema deleted/deletedAt condition", () => {
  it("keeps deleted in the root-level required list", () => {
    expect(schema.required).toContain("deleted");
  });

  it("keeps additionalProperties closed", () => {
    expect(schema.additionalProperties).toBe(false);
  });

  it("requires deleted in both conditional if branches", () => {
    const conditionals = (schema.allOf ?? []).filter((c) => c.if !== undefined);
    expect(conditionals).toHaveLength(2);
    for (const clause of conditionals) {
      expect(clause.if?.["required"]).toContain("deleted");
    }
  });

  it("missing deleted fails only on the required field, not the deletedAt condition", () => {
    const errors = validate({});
    expect(errors).toContain("missing required field: deleted");
    expect(errors.some((e) => e.includes("deletedAt"))).toBe(false);
  });

  it("deleted=true with missing or null deletedAt still fails", () => {
    expect(validate({ deleted: true })).toContain("then required field: deletedAt");
    expect(validate({ deleted: true, deletedAt: null })).toContain("then required field: deletedAt");
  });

  it("deleted=false with a date deletedAt fails", () => {
    const errors = validate({ deleted: false, deletedAt: "2026-08-21T04:00:00Z" });
    expect(errors).toContain("deletedAt must be null when deleted is false");
  });

  it("deleted=false with deletedAt=null passes the deletedAt condition", () => {
    const errors = validate({ deleted: false, deletedAt: null });
    expect(errors.some((e) => e.includes("deletedAt"))).toBe(false);
  });
});
