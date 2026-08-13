import { Module } from "@nestjs/common";
import { AppController } from "./app.controller";
import { MetricsController } from "./metrics.controller";
import { DataQualityModule } from "./modules/data-quality/data-quality.module";
import { EmotionModule } from "./modules/emotion/emotion.module";

@Module({
  imports: [DataQualityModule, EmotionModule],
  controllers: [AppController, MetricsController],
})
export class AppModule {}
