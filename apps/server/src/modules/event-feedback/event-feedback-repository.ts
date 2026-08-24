import type { EventFeedback } from "@kunlun/shared-types";
import type { EventFeedbackQuery } from "./event-feedback-validation";

export type AppendDisposition = "INSERTED" | "EXISTING";

export interface AppendFeedbackResult {
  disposition: AppendDisposition;
  feedback: EventFeedback;
}

export interface EventFeedbackRepository {
  append(feedback: EventFeedback): Promise<AppendFeedbackResult>;
  list(query: EventFeedbackQuery): Promise<EventFeedback[]>;
}
