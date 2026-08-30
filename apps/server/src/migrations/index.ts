import { migrations as initial } from "./001-initial";
import { migrations as eventFeedback } from "./002-event-feedback";
import { migrations as eventIntelligence } from "./003-event-intelligence";
import { migrations as claimReview } from "./004-kol-claim-review";
import { migrations as instrumentMasterIntelligence } from "./005-instrument-master-intelligence";
import { migrations as sectorIntelligence } from "./006-sector-intelligence";
import { migrations as seatKolIntelligence } from "./007-seat-kol-intelligence";
import { migrations as watchlistAlerts } from "./008-watchlist-alerts";
import { migrations as auth } from "./009-auth";
import { migrations as notificationReceipts } from "./010-watchlist-notification-receipts";

export const migrations = [
  ...initial,
  ...eventFeedback,
  ...eventIntelligence,
  ...claimReview,
  ...instrumentMasterIntelligence,
  ...sectorIntelligence,
  ...seatKolIntelligence,
  ...watchlistAlerts,
  ...auth,
  ...notificationReceipts,
];
