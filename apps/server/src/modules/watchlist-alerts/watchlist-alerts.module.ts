import { Module } from "@nestjs/common";
import { InMemoryWatchlistAlertsRepository } from "./in-memory-watchlist-alerts.repository";
import { InAppWatchlistAlertNotificationDispatcher } from "./watchlist-alerts.notification";
import { PostgresWatchlistAlertsRepository } from "./postgres-watchlist-alerts.repository";
import { WatchlistAlertsController } from "./watchlist-alerts.controller";
import { WatchlistAlertsService } from "./watchlist-alerts.service";
import {
  WATCHLIST_ALERTS_NOTIFICATION,
  WATCHLIST_ALERTS_OWNER_REF,
  WATCHLIST_ALERTS_REPOSITORY,
} from "./watchlist-alerts.tokens";

@Module({
  controllers: [WatchlistAlertsController],
  providers: [
    WatchlistAlertsService,
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
  ],
  exports: [WatchlistAlertsService],
})
export class WatchlistAlertsModule {}
