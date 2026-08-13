import { Module } from "@nestjs/common";
import { AppController } from "./app.controller";
import { MetricsController } from "./metrics.controller";

@Module({
  imports: [],
  controllers: [AppController, MetricsController],
})
export class AppModule {}
