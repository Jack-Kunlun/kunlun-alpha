import { describe, expect, it } from "vitest";

import signalSchema from "../../schemas/strategy/signal.json";
import descriptorSchema from "../../schemas/strategy/strategy-descriptor.json";
import { parseStrategyDescriptor, parseStrategySignal } from "./validators";

type JsonSchema = {
  additionalProperties?: boolean;
  properties?: Record<string, JsonSchema & { const?: unknown; enum?: unknown[]; pattern?: string }>;
  required?: string[];
};

describe("strategy contracts", () => {
  it("keeps Signal versioned, point-in-time and permanently non-executable", () => {
    const schema = signalSchema as JsonSchema;

    expect(schema.additionalProperties).toBe(false);
    expect(schema.required).toEqual(
      expect.arrayContaining([
        "schemaVersion",
        "strategyId",
        "strategyVersion",
        "algorithmVersion",
        "entityId",
        "decisionTime",
        "dataCutoffTime",
        "direction",
        "score",
        "confidence",
        "inputSnapshotId",
        "inputSnapshotVersion",
        "isExecutable",
        "executionCapability",
      ]),
    );
    expect(schema.properties?.["isExecutable"]?.const).toBe(false);
    expect(schema.properties?.["executionCapability"]?.const).toBe("NONE");
    expect(schema.properties?.["direction"]?.enum).toEqual(["LONG", "SHORT", "NEUTRAL"]);
    for (const forbidden of [
      "accountId",
      "broker",
      "clientOrderId",
      "limitPrice",
      "orderId",
      "quantity",
    ]) {
      expect(schema.properties?.[forbidden]).toBeUndefined();
    }
  });

  it("describes only research lifecycle, PIT features and typed parameters", () => {
    const schema = descriptorSchema as JsonSchema;

    expect(schema.additionalProperties).toBe(false);
    expect(schema.required).toEqual(
      expect.arrayContaining([
        "schemaVersion",
        "strategyId",
        "strategyVersion",
        "algorithmVersion",
        "sdkVersion",
        "lifecycleVersion",
        "requiredFeatures",
        "parameterSpecs",
      ]),
    );
    expect(schema.properties?.["execution"] ?? schema.properties?.["broker"]).toBeUndefined();
  });

  it("parses immutable Signal payloads and rejects semantic or execution drift", () => {
    const payload = {
      schemaVersion: "signal-v1",
      signalId: "signal:momentum:600001.SH:20260601",
      strategyId: "momentum.research",
      strategyVersion: "1.0.0",
      algorithmVersion: "1.0.0",
      entityId: "600001.SH",
      decisionTime: "2026-06-01T07:00:00Z",
      dataCutoffTime: "2026-06-01T06:59:00Z",
      direction: "LONG",
      score: "0.7",
      confidence: "0.8",
      horizonSessions: 20,
      rationale: "Point-in-time momentum research signal.",
      inputSnapshotId: "strategy-context:2026-06-01",
      inputSnapshotVersion: "1.0.0",
      evidenceIds: ["feature:momentum.window_20d:600001.SH"],
      isExecutable: false,
      executionCapability: "NONE",
    };

    const parsed = parseStrategySignal(payload);
    expect(Object.isFrozen(parsed)).toBe(true);
    expect(Object.isFrozen(parsed.evidenceIds)).toBe(true);
    expect(() =>
      parseStrategySignal({
        ...payload,
        dataCutoffTime: "2026-06-01T07:01:00Z",
      }),
    ).toThrow(/dataCutoffTime/);
    expect(() => parseStrategySignal({ ...payload, isExecutable: true })).toThrow(/isExecutable/);
    expect(() => parseStrategySignal({ ...payload, quantity: 100 })).toThrow(/quantity/);
    expect(() => parseStrategySignal({ ...payload, evidenceIds: ["same", "same"] })).toThrow(
      /evidenceIds/,
    );
    expect(() =>
      parseStrategySignal({ ...payload, score: "1.0000000000000000000000000000000001" }),
    ).toThrow(/score/);
    expect(() => parseStrategySignal({ ...payload, evidenceIds: ["e".repeat(513)] })).toThrow(
      /evidenceIds/,
    );
  });

  it("parses descriptor parameter associations and exact lifecycle hooks", () => {
    const payload = {
      schemaVersion: "strategy-descriptor-v1",
      strategyId: "momentum.research",
      strategyVersion: "1.0.0",
      algorithmVersion: "1.0.0",
      sdkVersion: "1.0.0",
      lifecycleVersion: "1.0.0",
      description: "Point-in-time momentum research strategy",
      requiredFeatures: ["momentum.window_20d"],
      parameterSpecs: [
        {
          name: "lookback",
          valueType: "INTEGER",
          required: true,
          description: "Research lookback sessions",
          minimum: 1,
          maximum: 250,
        },
      ],
      lifecycleHooks: ["initialize", "onDecision", "finalize"],
      signalSchemaVersion: "signal-v1",
      executionCapability: "NONE",
    };

    const parsed = parseStrategyDescriptor(payload);
    expect(Object.isFrozen(parsed.parameterSpecs[0])).toBe(true);
    expect(() => parseStrategyDescriptor({ ...payload, lifecycleHooks: ["onDecision"] })).toThrow(
      /lifecycleHooks/,
    );
    expect(() =>
      parseStrategyDescriptor({
        ...payload,
        parameterSpecs: [{ ...payload.parameterSpecs[0], defaultValue: "20" }],
      }),
    ).toThrow(/INTEGER/);
    expect(() =>
      parseStrategyDescriptor({
        ...payload,
        parameterSpecs: [
          {
            ...payload.parameterSpecs[0],
            valueType: "DECIMAL",
            defaultValue: "9007199254740993",
            minimum: "0",
            maximum: "9007199254740992",
          },
        ],
      }),
    ).toThrow(/default exceeds maximum/);
    expect(() =>
      parseStrategyDescriptor({
        ...payload,
        requiredFeatures: ["f".repeat(257)],
      }),
    ).toThrow(/requiredFeatures/);
  });
});
