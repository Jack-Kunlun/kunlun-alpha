import { migrations as initial } from "./001-initial";
import { migrations as eventFeedback } from "./002-event-feedback";
import { migrations as eventIntelligence } from "./003-event-intelligence";

export const migrations = [...initial, ...eventFeedback, ...eventIntelligence];
