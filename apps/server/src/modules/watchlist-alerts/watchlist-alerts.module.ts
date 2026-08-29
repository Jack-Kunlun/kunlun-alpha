import { Module } from "@nestjs/common";
import { InstrumentIntelligenceModule } from "../instrument-intelligence/instrument-intelligence.module";
import { InMemoryWatchlistAlertsRepository } from "./in-memory-watchlist-alerts.repository";
import { InAppWatchlistAlertNotificationDispatcher } from "./watchlist-alerts.notification";
import { PostgresWatchlistAlertsRepository } from "./postgres-watchlist-alerts.repository";
import { WatchlistAlertsController } from "./watchlist-alerts.controller";
import { WatchlistAlertsEvaluationRunner } from "./watchlist-alerts.evaluation-runner";
import { WatchlistAlertsService } from "./watchlist-alerts.service";
import {
  WATCHLIST_ALERTS_NOTIFICATION,
  WATCHLIST_ALERTS_OWNER_REF,
  WATCHLIST_ALERTS_EVALUATION_INTERVAL_MS,
  WATCHLIST_ALERTS_REPOSITORY,
} from "./watchlist-alerts.tokens";

@Module({
  imports: [InstrumentIntelligenceModule],
  controllers: [WatchlistAlertsController],
  providers: [
    WatchlistAlertsService,
    WatchlistAlertsEvaluationRunner,
    {
      provide: WATCHLIST_ALERTS_REPOSITORY,
      useFactory: () => {
        const connectionString = process.env.WATCHLIST_ALERTS_POSTGRES_DSN?.trim();
        const ownerRef = process.env.WATCHLIST_ALERTS_OWNER_REF?.trim();
        if (connectionString) return new PostgresWatchlistAlertsRepository(connectionString);
        if (ownerRef) {
          throw new Error("WATCHLIST_ALERTS_POSTGRES_DSN is required when alerts are enabled");
        }
        return new InMemoryWatchlistAlertsRepository();
      },
    },
    {
      provide: WATCHLIST_ALERTS_NOTIFICATION,
      useClass: InAppWatchlistAlertNotificationDispatcher,
    },
    {
      provide: WATCHLIST_ALERTS_OWNER_REF,
      useFactory: () => process.env.WATCHLIST_ALERTS_OWNER_REF ?? "",
    },
    {
      provide: WATCHLIST_ALERTS_EVALUATION_INTERVAL_MS,
      useFactory: () =>
        evaluationIntervalMs(process.env.WATCHLIST_ALERTS_EVALUATION_INTERVAL_SECONDS),
    },
  ],
  exports: [WatchlistAlertsService],
})
export class WatchlistAlertsModule {}

function evaluationIntervalMs(value: string | undefined): number {
  if (value === undefined || value.trim() === "" || value.trim() === "0") return 0;
  const seconds = Number(value);
  if (!Number.isSafeInteger(seconds) || seconds < 10 || seconds > 3600) {
    throw new Error(
      "WATCHLIST_ALERTS_EVALUATION_INTERVAL_SECONDS must be 0 or between 10 and 3600",
    );
  }
  return seconds * 1000;
}
