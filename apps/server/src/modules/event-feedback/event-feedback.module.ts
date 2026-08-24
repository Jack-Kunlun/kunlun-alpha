import { Module } from "@nestjs/common";
import { Pool } from "pg";
import { DenyAllEventFeedbackAuthorizer } from "./event-feedback-authorizer";
import { EventFeedbackController } from "./event-feedback.controller";
import type { EventFeedbackRepository } from "./event-feedback-repository";
import { EventFeedbackService, SystemEventFeedbackClock } from "./event-feedback.service";
import {
  EVENT_FEEDBACK_AUTHORIZER,
  EVENT_FEEDBACK_CLOCK,
  EVENT_FEEDBACK_REPOSITORY,
} from "./event-feedback.tokens";
import { PostgresEventFeedbackRepository } from "./postgres-event-feedback.repository";

function buildRepository(): EventFeedbackRepository {
  const dsn = process.env["EVENT_FEEDBACK_POSTGRES_DSN"];
  if (!dsn) throw new Error("EVENT_FEEDBACK_POSTGRES_DSN is required for event feedback");
  return new PostgresEventFeedbackRepository(new Pool({ connectionString: dsn }));
}

@Module({
  controllers: [EventFeedbackController],
  providers: [
    { provide: EVENT_FEEDBACK_REPOSITORY, useFactory: buildRepository },
    { provide: EVENT_FEEDBACK_AUTHORIZER, useClass: DenyAllEventFeedbackAuthorizer },
    { provide: EVENT_FEEDBACK_CLOCK, useClass: SystemEventFeedbackClock },
    EventFeedbackService,
  ],
  exports: [EventFeedbackService],
})
export class EventFeedbackModule {}
