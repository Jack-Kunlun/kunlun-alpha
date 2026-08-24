import { ConflictException, ForbiddenException, Inject, Injectable } from "@nestjs/common";
import type { EventFeedback, EventFeedbackSubmission } from "@kunlun/shared-types";
import { createHash } from "node:crypto";
import {
  DenyAllEventFeedbackAuthorizer,
  type EventFeedbackAuthorizer,
} from "./event-feedback-authorizer";
import type { EventFeedbackRepository } from "./event-feedback-repository";
import {
  EVENT_FEEDBACK_AUTHORIZER,
  EVENT_FEEDBACK_CLOCK,
  EVENT_FEEDBACK_REPOSITORY,
} from "./event-feedback.tokens";
import {
  validateFeedbackQuery,
  validateFeedbackSubmission,
  validateReviewerRef,
} from "./event-feedback-validation";

export interface EventFeedbackClock {
  now(): Date;
}

export class SystemEventFeedbackClock implements EventFeedbackClock {
  now(): Date {
    return new Date();
  }
}

function digest(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function submissionIdentity(input: EventFeedbackSubmission, reviewerRef: string): string {
  return JSON.stringify({ reviewerRef, ...input });
}

@Injectable()
export class EventFeedbackService {
  constructor(
    @Inject(EVENT_FEEDBACK_REPOSITORY)
    private readonly repository: EventFeedbackRepository,
    @Inject(EVENT_FEEDBACK_AUTHORIZER)
    private readonly authorizer: EventFeedbackAuthorizer = new DenyAllEventFeedbackAuthorizer(),
    @Inject(EVENT_FEEDBACK_CLOCK)
    private readonly clock: EventFeedbackClock = new SystemEventFeedbackClock(),
  ) {}

  async submit(value: unknown): Promise<EventFeedback> {
    const reviewerRef = await this.reviewer();
    const input = validateFeedbackSubmission(value);
    const submissionFingerprint = digest(submissionIdentity(input, reviewerRef));
    const feedbackId = digest(`${reviewerRef}\u001f${input.clientRequestId}`);
    const timestamp = this.clock.now().toISOString();
    const feedback: EventFeedback = {
      ...input,
      schemaVersion: "event-feedback-v1",
      feedbackId,
      reviewerRef,
      submissionFingerprint,
      createdAt: timestamp,
      availableAt: timestamp,
    };
    const appended = await this.repository.append(feedback);
    if (
      appended.disposition === "EXISTING" &&
      appended.feedback.submissionFingerprint !== submissionFingerprint
    ) {
      throw new ConflictException("clientRequestId was already used for different feedback");
    }
    return appended.feedback;
  }

  async list(query: unknown): Promise<EventFeedback[]> {
    await this.reviewer();
    return this.repository.list(validateFeedbackQuery(query));
  }

  private async reviewer(): Promise<string> {
    const reviewerRef = await this.authorizer.currentReviewerRef();
    if (reviewerRef === null) throw new ForbiddenException("无权访问事件反馈");
    return validateReviewerRef(reviewerRef);
  }
}
