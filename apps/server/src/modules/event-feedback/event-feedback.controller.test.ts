import { BadRequestException } from "@nestjs/common";
import { describe, expect, it } from "vitest";
import { EventFeedbackController } from "./event-feedback.controller";
import { InMemoryEventFeedbackRepository } from "./in-memory-event-feedback.repository";
import { EventFeedbackService } from "./event-feedback.service";

function controller(): EventFeedbackController {
  return new EventFeedbackController(
    new EventFeedbackService(
      new InMemoryEventFeedbackRepository(),
      { currentReviewerRef: async () => "reviewer-1" },
      { now: () => new Date("2026-08-24T06:00:00.000Z") },
    ),
  );
}

describe("EventFeedbackController", () => {
  it("maps malformed bodies to 400", async () => {
    await expect(controller().submit({ action: "CONFIRM" })).rejects.toThrow(
      BadRequestException,
    );
  });

  it("maps unknown query filters to 400", async () => {
    await expect(controller().list({ rawSql: "DROP TABLE" })).rejects.toThrow(
      BadRequestException,
    );
  });
});
