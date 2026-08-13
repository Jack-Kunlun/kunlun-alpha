import { Controller, Get, Query } from "@nestjs/common";
import { ApiOperation, ApiTags } from "@nestjs/swagger";
import type { DataQualityRecord } from "./quality-record";
import type { QualityQuery } from "./data-quality.service";
import type { DataQualityService } from "./data-quality.service";

@ApiTags("data-quality")
@Controller("data-quality")
export class DataQualityController {
  constructor(private readonly service: DataQualityService) {}

  @Get()
  @ApiOperation({ summary: "List data quality records, filterable by date/source/instrument" })
  list(@Query() query: QualityQuery): DataQualityRecord[] {
    return this.service.query(query);
  }
}
