import { describe, expect, it } from "vitest";

import feedbackSchema from "../../schemas/event/event-feedback.json";
import submissionSchema from "../../schemas/event/event-feedback-submission.json";

describe("event feedback contracts", () => {
  it("keeps submission and persisted record on explicit immutable versions", () => {
    expect(submissionSchema.title).toBe("EventFeedbackSubmission");
    expect(feedbackSchema.title).toBe("EventFeedback");
    expect(JSON.stringify(submissionSchema)).toContain("event-feedback-submission-v1");
    expect(JSON.stringify(feedbackSchema)).toContain("event-feedback-v1");
  });

  it("requires corrections only for CORRECT feedback", () => {
    for (const schema of [submissionSchema, feedbackSchema]) {
      const encoded = JSON.stringify(schema);
      expect(encoded).toContain('"const":"CORRECT"');
      expect(encoded).toContain('"required":["correction"]');
      expect(encoded).toContain('"not":{"required":["correction"]}');
    }
  });

  it("binds feedback to an event and model configuration fingerprint", () => {
    const encoded = JSON.stringify(feedbackSchema);
    expect(encoded).toContain('"eventId"');
    expect(encoded).toContain('"modelConfigurationFingerprint"');
    expect(encoded).toContain('"submissionFingerprint"');
    expect(encoded).toContain('"availableAt"');
  });
});
