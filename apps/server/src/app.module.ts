import { Module } from "@nestjs/common";
import { AppController } from "./app.controller";
import { MetricsController } from "./metrics.controller";
import { DataQualityModule } from "./modules/data-quality/data-quality.module";
import { EmotionModule } from "./modules/emotion/emotion.module";
import { EventFeedbackModule } from "./modules/event-feedback/event-feedback.module";
import { EventIntelligenceModule } from "./modules/event-intelligence/event-intelligence.module";
import { ClaimReviewModule } from "./modules/claim-review/claim-review.module";
import { SeatKolWorkbenchModule } from "./modules/seat-kol/seat-kol.module";

@Module({
  imports: [
    DataQualityModule,
    EmotionModule,
    EventFeedbackModule,
    EventIntelligenceModule,
    ClaimReviewModule,
    SeatKolWorkbenchModule,
  ],
  controllers: [AppController, MetricsController],
})
export class AppModule {}
