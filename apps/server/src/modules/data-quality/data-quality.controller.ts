import { BadRequestException, Controller, Get, Inject, Param, Query } from "@nestjs/common";
import { ApiExtraModels, ApiOperation, ApiTags } from "@nestjs/swagger";
import type { MarketCoverageResponse } from "@kunlun/shared-types";
import type { DataQualityRecord, EvidenceRecord } from "./quality-record";
import { QualityValidationError } from "./quality-filters";
import { DataQualityService } from "./data-quality.service";
import { QualityQueryDto } from "./quality-dto";
import { MarketCoverageQueryDto } from "./market-coverage.dto";
import { MarketCoverageValidationError } from "./market-coverage.query";

@ApiTags("data-quality")
@ApiExtraModels(QualityQueryDto, MarketCoverageQueryDto)
@Controller("data-quality")
export class DataQualityController {
  constructor(@Inject(DataQualityService) private readonly service: DataQualityService) {}

  @Get()
  @ApiOperation({ summary: "List persisted quality events with validated filters" })
  async list(@Query() query: QualityQueryDto): Promise<DataQualityRecord[]> {
    try {
      return await this.service.query(query);
    } catch (error) {
      if (error instanceof QualityValidationError) {
        throw new BadRequestException(error.message);
      }
      throw error;
    }
  }

  @Get("market-coverage")
  @ApiOperation({ summary: "Read observed daily market-bar coverage" })
  async coverage(@Query() query: MarketCoverageQueryDto): Promise<MarketCoverageResponse> {
    try {
      return await this.service.coverage(query);
    } catch (error) {
      if (error instanceof MarketCoverageValidationError) {
        throw new BadRequestException(error.message);
      }
      throw error;
    }
  }

  @Get(":id/evidence")
  @ApiOperation({ summary: "Fetch a safe evidence record by internal id" })
  async evidence(@Param("id") id: string): Promise<EvidenceRecord | null> {
    try {
      return await this.service.getEvidence(id);
    } catch (error) {
      if (error instanceof QualityValidationError) {
        throw new BadRequestException(error.message);
      }
      throw error;
    }
  }
}
