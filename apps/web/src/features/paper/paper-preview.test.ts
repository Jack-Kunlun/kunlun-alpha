import { describe, expect, it } from "vitest";
import { buildPaperPreviewCommand, readPaperPreview } from "./paper-preview";

const form = {
  instrumentId: "600519.sh",
  price: "100.00",
  score: "1",
  confidence: "1",
  lotSize: "100",
};
const accountId = "a".repeat(64);
function response() {
  return {
    schemaVersion: "paper-allocation-decision-v1",
    dataMeaning: "INTENT_ONLY_NO_BROKER_PATH",
    executionCapability: "PAPER_ONLY",
    accountId,
    decisionTime: "2026-10-25T02:00:00.123456Z",
    policyId: "paper-preview-allocation",
    policyVersion: "1.0.0",
    targets: [
      {
        instrumentId: "600519.SH",
        currentQuantity: 0,
        targetQuantity: 300,
        targetWeight: "0.3",
        referencePrice: "100",
        roundingLotSize: 100,
      },
    ],
    intents: [
      {
        instrumentId: "600519.SH",
        side: "BUY",
        quantity: 300,
        targetQuantity: 300,
        referencePrice: "100",
        brokerExecutable: false,
        executionCapability: "PAPER_ONLY",
      },
    ],
    rejections: [],
  };
}

describe("paper preview form and displayed values", () => {
  it("normalizes canonical symbols while retaining exact price input", () => {
    const r = buildPaperPreviewCommand(form, "preview-request-1");
    expect(r.error).toBeNull();
    expect(r.command?.instrumentId).toBe("600519.SH");
    expect(r.command?.price).toBe("100.00");
  });
  it.each([
    { price: "0" },
    { price: "1e3" },
    { price: "9".repeat(33) },
    { instrumentId: "sh600519" },
    { score: "1.1" },
    { confidence: "-1" },
    { lotSize: "0" },
    { lotSize: "10001" },
    { lotSize: "1.5" },
  ])("rejects unsupported scenario input %j", (changes) => {
    expect(
      buildPaperPreviewCommand({ ...form, ...changes }, "preview-request-1").command,
    ).toBeNull();
  });
  it("shows exact hypothetical notional without converting prices to floating point", () => {
    const command = buildPaperPreviewCommand(form, "preview-request-1").command;
    if (command === null) throw new Error("invalid fixture");
    expect(readPaperPreview(response(), command, accountId)).toMatchObject({
      kind: "target",
      quantity: 300,
      notional: "30000",
      price: "100",
    });
    const fractional = { ...command, price: "100.000000000000000001" };
    const value = response();
    value.targets[0]!.referencePrice = fractional.price;
    value.intents[0]!.referencePrice = fractional.price;
    expect(readPaperPreview(value, fractional, accountId)).toMatchObject({
      notional: "30000.0000000000000003",
    });
  });
  it("labels rejections without exposing internal codes", () => {
    const command = buildPaperPreviewCommand(form, "preview-request-1").command;
    if (command === null) throw new Error();
    const value = {
      ...response(),
      targets: [],
      intents: [],
      rejections: [{ instrumentId: "600519.SH", reason: "LOW_CONFIDENCE" }],
    };
    expect(readPaperPreview(value, command, accountId)).toMatchObject({
      kind: "rejected",
      reason: "假设可信度低于 0.5。",
    });
  });
  it.each(["account", "price", "broker", "quantity"])(
    "refuses mismatched %s responses",
    (field) => {
      const command = buildPaperPreviewCommand(form, "preview-request-1").command;
      if (command === null) throw new Error();
      const value = response();
      if (field === "account") value.accountId = "b".repeat(64);
      if (field === "price") value.targets[0]!.referencePrice = "200";
      if (field === "broker") value.intents[0]!.brokerExecutable = true;
      if (field === "quantity") value.intents[0]!.quantity = 2 ** 53;
      expect(() => readPaperPreview(value, command, accountId)).toThrow();
    },
  );
});
