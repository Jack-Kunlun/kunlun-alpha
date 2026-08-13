import { Module } from "@nestjs/common";
import { DataQualityController } from "./data-quality.controller";
import { DATA_QUALITY_RECORDS, DataQualityService } from "./data-quality.service";

@Module({
  controllers: [DataQualityController],
  providers: [DataQualityService, { provide: DATA_QUALITY_RECORDS, useValue: [] }],
  exports: [DataQualityService],
})
export class DataQualityModule {}
