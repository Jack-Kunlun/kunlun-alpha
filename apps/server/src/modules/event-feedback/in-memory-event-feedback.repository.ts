import type { EventFeedback } from "@kunlun/shared-types";
import type {
  AppendFeedbackResult,
  EventFeedbackRepository,
} from "./event-feedback-repository";
import type { EventFeedbackQuery } from "./event-feedback-validation";

export class InMemoryEventFeedbackRepository implements EventFeedbackRepository {
  private readonly records = new Map<string, EventFeedback>();

  constructor(initial: EventFeedback[] = []) {
    for (const feedback of initial) this.records.set(feedback.feedbackId, feedback);
  }

  async append(feedback: EventFeedback): Promise<AppendFeedbackResult> {
    const existing = this.records.get(feedback.feedbackId);
    if (existing) return { disposition: "EXISTING", feedback: existing };
    this.records.set(feedback.feedbackId, feedback);
    return { disposition: "INSERTED", feedback };
  }

  async list(query: EventFeedbackQuery): Promise<EventFeedback[]> {
    return [...this.records.values()]
      .filter(
        (item) =>
          (query.eventId === undefined || item.eventId === query.eventId) &&
          (query.modelConfigurationFingerprint === undefined ||
            item.modelConfigurationFingerprint === query.modelConfigurationFingerprint),
      )
      .sort(
        (left, right) =>
          right.createdAt.localeCompare(left.createdAt) || left.feedbackId.localeCompare(right.feedbackId),
      )
      .slice(0, query.limit);
  }
}
