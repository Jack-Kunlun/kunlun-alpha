import { Module } from "@nestjs/common";
import { AppController } from "./app.controller";
import { MetricsController } from "./metrics.controller";
import { DataQualityModule } from "./modules/data-quality/data-quality.module";

@Module({
  imports: [DataQualityModule],
  controllers: [AppController, MetricsController],
})
export class AppModule {}
