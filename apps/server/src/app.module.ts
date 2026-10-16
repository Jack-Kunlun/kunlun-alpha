import { Module } from "@nestjs/common";
import { AppController } from "./app.controller";
import { MetricsController } from "./metrics.controller";
import { DataQualityModule } from "./modules/data-quality/data-quality.module";
import { EmotionModule } from "./modules/emotion/emotion.module";
import { EventFeedbackModule } from "./modules/event-feedback/event-feedback.module";
import { EventIntelligenceModule } from "./modules/event-intelligence/event-intelligence.module";
import { ClaimReviewModule } from "./modules/claim-review/claim-review.module";
import { SeatKolWorkbenchModule } from "./modules/seat-kol/seat-kol.module";
import { BacktestRegressionModule } from "./modules/backtest-regression/backtest-regression.module";
import { DashboardModule } from "./modules/dashboard/dashboard.module";
import { LimitPoolModule } from "./modules/limit-pool/limit-pool.module";
import { InstrumentIntelligenceModule } from "./modules/instrument-intelligence/instrument-intelligence.module";
import { WatchlistAlertsModule } from "./modules/watchlist-alerts/watchlist-alerts.module";
import { PreciousMetalsModule } from "./modules/precious-metals/precious-metals.module";
import { PaperTerminalModule } from "./modules/paper/paper-terminal.module";
import { RankingTerminalModule } from "./modules/ranking/ranking-terminal.module";
import { AuthModule } from "./modules/auth/auth.module";
import { MarketDataSettingsModule } from "./modules/market-data-settings/market-data-settings.module";
import { MarketDataStatusModule } from "./modules/market-data-status/market-data-status.module";

@Module({
  imports: [
    AuthModule,
    MarketDataSettingsModule,
    MarketDataStatusModule,
    DataQualityModule,
    EmotionModule,
    EventFeedbackModule,
    EventIntelligenceModule,
    ClaimReviewModule,
    SeatKolWorkbenchModule,
    BacktestRegressionModule,
    DashboardModule,
    LimitPoolModule,
    InstrumentIntelligenceModule,
    WatchlistAlertsModule,
    PreciousMetalsModule,
    PaperTerminalModule,
    RankingTerminalModule,
  ],
  controllers: [AppController, MetricsController],
})
export class AppModule {}
