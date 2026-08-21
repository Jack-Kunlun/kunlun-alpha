import { describe, expect, it } from "vitest";

// @ts-expect-error -- .mjs generator module has no TypeScript declaration
import { stripConditionalAllOf } from "../scripts/gen-typescript.mjs";

describe("stripConditionalAllOf", () => {
  it("removes allOf elements carrying if/then/else constraints", () => {
    const schema = {
      type: "object",
      additionalProperties: false,
      allOf: [
        { if: { properties: { deleted: { const: true } } }, then: { required: ["deletedAt"] } },
        { properties: { extra: { type: "string" } } },
      ],
    };
    const result = stripConditionalAllOf(schema);
    expect(result.allOf).toEqual([{ properties: { extra: { type: "string" } } }]);
  });

  it("deletes allOf entirely when only conditional elements remain", () => {
    const schema = { allOf: [{ if: {}, then: {} }, { if: {}, else: {} }] };
    const result = stripConditionalAllOf(schema);
    expect("allOf" in result).toBe(false);
  });

  it("leaves schemas without conditional allOf untouched", () => {
    const schema = { type: "object", additionalProperties: false };
    expect(stripConditionalAllOf(schema)).toBe(schema);
  });

  it("does not mutate the input schema", () => {
    const schema = {
      allOf: [{ if: {}, then: {} }, { properties: { x: { type: "string" } } }],
    };
    const copy = JSON.parse(JSON.stringify(schema));
    stripConditionalAllOf(schema);
    expect(schema).toEqual(copy);
  });
});
