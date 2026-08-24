export interface EmotionAuthorizer {
  canAccess(): boolean | Promise<boolean>;
}

export class AllowAllEmotionAuthorizer implements EmotionAuthorizer {
  canAccess(): boolean {
    return true;
  }
}
