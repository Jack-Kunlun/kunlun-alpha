import { createHash } from "node:crypto";

import { describe, expect, it } from "vitest";

import featureSpecVector from "../../fixtures/feature/feature-spec-v1.json";
import featureSpecSchema from "../../schemas/feature/feature-spec.json";

type JsonSchema = {
  additionalProperties?: boolean | JsonSchema;
  type?: string;
  propertyNames?: { pattern?: string };
  properties?: Record<
    string,
    JsonSchema & { pattern?: string; minLength?: number; maxLength?: number }
  >;
  required?: string[];
};

const schema = featureSpecSchema as JsonSchema;

describe("FeatureSpec schema", () => {
  it("requires ownership, point-in-time semantics, dependencies and fingerprint", () => {
    expect(schema.required).toEqual(
      expect.arrayContaining([
        "schemaVersion",
        "name",
        "version",
        "entity",
        "frequency",
        "valueType",
        "owner",
        "description",
        "algorithmVersion",
        "calculationDefinition",
        "windowDefinition",
        "filterPolicyVersion",
        "pitPolicyVersion",
        "eventTimeField",
        "availableTimeField",
        "availabilityPolicy",
        "dependencies",
        "sourceContracts",
        "semanticFingerprint",
      ]),
    );
    expect(schema.properties?.["owner"]?.minLength).toBe(1);
  });

  it("closes the object and pins machine-checkable versions", () => {
    expect(schema.additionalProperties).toBe(false);
    expect(schema.properties?.["version"]?.pattern).toBe("^v[1-9][0-9]*$");
    expect(schema.properties?.["version"]?.maxLength).toBe(16);
    expect(schema.properties?.["semanticFingerprint"]?.pattern).toBe("^sha256:[0-9a-f]{64}$");
  });

  it("requires exact dependency names and versions", () => {
    const dependencies = schema.properties?.["dependencies"] as JsonSchema;
    expect(dependencies.type).toBe("object");
    expect(dependencies.additionalProperties).toMatchObject({
      type: "string",
      maxLength: 16,
      pattern: "^v[1-9][0-9]*$",
    });
  });

  it("keeps the cross-language semantic fingerprint vector stable", () => {
    const payload = featureSpecVector as Record<string, unknown>;
    const semanticPayload = {
      algorithmVersion: payload["algorithmVersion"],
      availabilityPolicy: payload["availabilityPolicy"],
      availableTimeField: payload["availableTimeField"],
      calculationDefinition: payload["calculationDefinition"],
      dependencies: payload["dependencies"],
      description: payload["description"],
      entity: payload["entity"],
      eventTimeField: payload["eventTimeField"],
      filterPolicyVersion: payload["filterPolicyVersion"],
      frequency: payload["frequency"],
      name: payload["name"],
      pitPolicyVersion: payload["pitPolicyVersion"],
      sourceContracts: payload["sourceContracts"],
      valueType: payload["valueType"],
      windowDefinition: payload["windowDefinition"],
    };
    const canonicalize = (value: unknown): unknown => {
      if (Array.isArray(value)) return value.map(canonicalize);
      if (value !== null && typeof value === "object") {
        return Object.fromEntries(
          Object.entries(value)
            .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
            .map(([key, entryValue]) => [key, canonicalize(entryValue)]),
        );
      }
      return value;
    };
    const fingerprint = `sha256:${createHash("sha256")
      .update(JSON.stringify(canonicalize(semanticPayload)), "utf8")
      .digest("hex")}`;

    expect(fingerprint).toBe(payload["semanticFingerprint"]);
  });

  it("forbids outer whitespace before fingerprinting", () => {
    expect(schema.properties?.["description"]?.pattern).toBe("^(?:\\S|\\S(?:[\\s\\S]*\\S))$");
  });
});
