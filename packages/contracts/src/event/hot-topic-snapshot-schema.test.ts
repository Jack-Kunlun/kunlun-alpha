import { describe, expect, it } from "vitest";
import hotTopicSchema from "../../schemas/event/hot-topic-snapshot.json";

describe("HotTopicSnapshot V1 schema", () => {
  it("is closed, versioned and point-in-time", () => {
    expect(hotTopicSchema.additionalProperties).toBe(false);
    expect(hotTopicSchema.required).toEqual(
      expect.arrayContaining([
        "snapshotId",
        "decisionTime",
        "windowStart",
        "windowEnd",
        "policyFingerprint",
        "algorithmVersion",
      ]),
    );
  });

  it("publishes integer score components and visible sample counts", () => {
    const properties = hotTopicSchema.properties;
    expect(properties.scoreBps.type).toBe("integer");
    expect(properties.confidenceBps.type).toBe("integer");
    expect(properties.components.additionalProperties).toBe(false);
    expect(properties.eventCount.type).toBe("integer");
    expect(properties.sourceCount.type).toBe("integer");
  });
});
