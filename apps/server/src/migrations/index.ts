import { migrations as initial } from "./001-initial";
import { migrations as eventFeedback } from "./002-event-feedback";
import { migrations as eventIntelligence } from "./003-event-intelligence";
import { migrations as claimReview } from "./004-kol-claim-review";

export const migrations = [...initial, ...eventFeedback, ...eventIntelligence, ...claimReview];
