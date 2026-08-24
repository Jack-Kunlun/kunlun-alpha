import { describe, expect, it } from "vitest";
import type { MarketEvent } from "./types";
import { buildFeedbackSubmission } from "./event-feedback";

const event = {
  eventId: "a".repeat(64),
  modelProvenance: { configurationFingerprint: "b".repeat(64) },
} as MarketEvent;

describe("buildFeedbackSubmission", () => {
  it("binds feedback to exact event and model configuration", () => {
    const result = buildFeedbackSubmission(
      event,
      {
        action: "CONFIRM",
        reasonCode: "ACCURATE",
        comment: "  已复核  ",
        correctedInstrumentId: "",
      },
      "request-1",
    );
    expect(result.eventId).toBe(event.eventId);
    expect(result.modelConfigurationFingerprint).toBe("b".repeat(64));
    expect(result.comment).toBe("已复核");
  });

  it("requires a canonical instrument for correction", () => {
    expect(() =>
      buildFeedbackSubmission(
        event,
        {
          action: "CORRECT",
          reasonCode: "WRONG_ENTITY",
          comment: "",
          correctedInstrumentId: "SH.600519",
        },
        "request-2",
      ),
    ).toThrow("规范证券代码");
  });
});
