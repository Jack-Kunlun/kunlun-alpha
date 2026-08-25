export interface ClaimReviewAuthorizer {
  currentReviewerRef(): Promise<string | null>;
}

export class DenyAllClaimReviewAuthorizer implements ClaimReviewAuthorizer {
  async currentReviewerRef(): Promise<null> {
    return null;
  }
}
