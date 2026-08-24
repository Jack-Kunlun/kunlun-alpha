import { apiClient } from "@/lib/api-client";
import type { EventFeedback, EventFeedbackSubmission, MarketEvent } from "./types";

export interface FeedbackDraft {
  action: EventFeedbackSubmission["action"];
  reasonCode: EventFeedbackSubmission["reasonCode"];
  comment: string;
  correctedInstrumentId: string;
}

export function buildFeedbackSubmission(
  event: MarketEvent,
  draft: FeedbackDraft,
  clientRequestId: string,
): EventFeedbackSubmission {
  const comment = draft.comment.trim();
  const correctedInstrumentId = draft.correctedInstrumentId.trim();
  if (draft.action === "CORRECT" && !/^[0-9]{6}\.(SH|SZ|BJ)$/.test(correctedInstrumentId)) {
    throw new Error("更正时必须填写规范证券代码");
  }
  return {
    schemaVersion: "event-feedback-submission-v1",
    clientRequestId,
    eventId: event.eventId,
    modelConfigurationFingerprint: event.modelProvenance.configurationFingerprint,
    action: draft.action,
    reasonCode: draft.reasonCode,
    ...(draft.action === "CORRECT"
      ? { correction: { instrumentIds: [correctedInstrumentId] } }
      : {}),
    ...(comment ? { comment } : {}),
  };
}

export async function submitEventFeedback(
  submission: EventFeedbackSubmission,
): Promise<EventFeedback> {
  return apiClient.post<EventFeedbackSubmission, EventFeedback>("/v1/event-feedback", submission);
}
