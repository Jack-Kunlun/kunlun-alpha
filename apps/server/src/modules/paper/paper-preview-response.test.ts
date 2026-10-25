import { describe, expect, it } from "vitest";
import { parsePaperPreviewResponse } from "./paper-preview-response";

export const previewCommand = {
  schemaVersion: "paper-terminal-simulation-v1" as const,
  clientRequestId: "preview-request-1",
  instrumentId: "600519.SH",
  price: "100.00",
  score: "1",
  confidence: "1",
  lotSize: 100,
};

export function previewResponse() {
  const common = {
    instrumentId: "600519.SH",
    sourceSignalIds: ["a".repeat(64)],
    referencePrice: "100",
    targetQuantity: 300,
    targetWeight: "0.3",
  };
  const policy = {
    policyId: "paper-preview-allocation",
    policyVersion: "1.0.0",
    policyDigest: "b".repeat(64),
  };
  return {
    schemaVersion: "paper-allocation-decision-v1",
    decisionId: "c".repeat(64),
    accountId: "d".repeat(64),
    decisionTime: "2026-10-25T02:00:00.123456Z",
    accountStateDigest: "e".repeat(64),
    ...policy,
    targets: [
      { ...common, currentQuantity: 0, roundingLotSize: 100, explanation: "按假设参考价试算" },
    ],
    intents: [
      {
        ...common,
        ...policy,
        schemaVersion: "paper-order-intent-v1",
        intentId: "f".repeat(64),
        accountId: "d".repeat(64),
        decisionTime: "2026-10-25T02:00:00.123456Z",
        side: "BUY",
        quantity: 300,
        explanation: "只读意图",
        brokerExecutable: false,
        executionCapability: "PAPER_ONLY",
      },
    ],
    rejections: [],
    decisionDigest: "1".repeat(64),
    executionCapability: "PAPER_ONLY",
    dataMeaning: "INTENT_ONLY_NO_BROKER_PATH",
  };
}

describe("paper preview boundary", () => {
  it("rejects a target calculated for different signal assumptions", () => {
    expect(() =>
      parsePaperPreviewResponse(previewResponse(), { ...previewCommand, score: "0.1" }),
    ).toThrow();
  });
  it("preserves exact decimal text and accepts equivalent input decimal scales", () => {
    const result = parsePaperPreviewResponse(previewResponse(), previewCommand);
    expect(result.targets[0]?.referencePrice).toBe("100");
    expect(result.intents[0]?.quantity).toBe(300);
  });
  it("accepts an explained rejection without a target or intent", () => {
    const value = {
      ...previewResponse(),
      targets: [],
      intents: [],
      rejections: [
        {
          instrumentId: "600519.SH",
          sourceSignalIds: ["a".repeat(64)],
          reason: "LOW_CONFIDENCE",
          explanation: "假设可信度低于门槛",
        },
      ],
    };
    expect(
      parsePaperPreviewResponse(value, { ...previewCommand, confidence: "0.1" }).rejections[0]
        ?.reason,
    ).toBe("LOW_CONFIDENCE");
  });
  it.each([
    ["0.1", "NO_ACTION"],
    ["1", "LOW_CONFIDENCE"],
  ])("refuses reason %s/%s inconsistent with confidence", (confidence, reason) => {
    const value = {
      ...previewResponse(),
      targets: [],
      intents: [],
      rejections: [
        {
          instrumentId: "600519.SH",
          sourceSignalIds: ["a".repeat(64)],
          reason,
          explanation: "不匹配的拒绝原因",
        },
      ],
    };
    expect(() => parsePaperPreviewResponse(value, { ...previewCommand, confidence })).toThrow();
  });
  it("preserves account precondition rejection precedence over confidence", () => {
    const value = {
      ...previewResponse(),
      targets: [],
      intents: [],
      rejections: [
        {
          instrumentId: "600519.SH",
          sourceSignalIds: ["a".repeat(64)],
          reason: "ACCOUNT_NOT_ACTIVE",
          explanation: "账户不可用",
        },
      ],
    };
    expect(
      parsePaperPreviewResponse(value, { ...previewCommand, confidence: "0.1" }).rejections[0]
        ?.reason,
    ).toBe("ACCOUNT_NOT_ACTIVE");
  });
  it.each([
    [
      "broker flag",
      (v: ReturnType<typeof previewResponse>) => {
        v.intents[0]!.brokerExecutable = true;
      },
    ],
    [
      "wrong instrument",
      (v: ReturnType<typeof previewResponse>) => {
        v.targets[0]!.instrumentId = "000001.SZ";
      },
    ],
    [
      "wrong price",
      (v: ReturnType<typeof previewResponse>) => {
        v.targets[0]!.referencePrice = "101";
      },
    ],
    [
      "unsafe quantity",
      (v: ReturnType<typeof previewResponse>) => {
        v.intents[0]!.quantity = 2 ** 53;
      },
    ],
    [
      "inconsistent delta",
      (v: ReturnType<typeof previewResponse>) => {
        v.intents[0]!.quantity = 200;
      },
    ],
    [
      "wrong account",
      (v: ReturnType<typeof previewResponse>) => {
        v.intents[0]!.accountId = "0".repeat(64);
      },
    ],
    [
      "wrong policy",
      (v: ReturnType<typeof previewResponse>) => {
        v.intents[0]!.policyVersion = "2.0.0";
      },
    ],
    [
      "bad date",
      (v: ReturnType<typeof previewResponse>) => {
        v.decisionTime = "2026-02-30T02:00:00Z";
      },
    ],
    [
      "excess weight",
      (v: ReturnType<typeof previewResponse>) => {
        v.targets[0]!.targetWeight = "0.8";
      },
    ],
  ])("rejects %s", (_label, change) => {
    const value = previewResponse();
    change(value);
    expect(() => parsePaperPreviewResponse(value, previewCommand)).toThrow();
  });
});
