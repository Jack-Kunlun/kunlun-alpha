export interface EventFeedbackAuthorizer {
  currentReviewerRef(): Promise<string | null>;
}

export class DenyAllEventFeedbackAuthorizer implements EventFeedbackAuthorizer {
  async currentReviewerRef(): Promise<null> {
    return null;
  }
}
