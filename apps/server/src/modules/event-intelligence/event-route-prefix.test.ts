import "reflect-metadata";

import { PATH_METADATA } from "@nestjs/common/constants";
import { describe, expect, it } from "vitest";

import { EventFeedbackController } from "../event-feedback/event-feedback.controller";
import { EventIntelligenceController } from "./event-intelligence.controller";

describe("event API route prefixes", () => {
  it("leaves API versioning to the application global prefix", () => {
    expect(Reflect.getMetadata(PATH_METADATA, EventIntelligenceController)).toBe(
      "event-intelligence",
    );
    expect(Reflect.getMetadata(PATH_METADATA, EventFeedbackController)).toBe("event-feedback");
  });
});
