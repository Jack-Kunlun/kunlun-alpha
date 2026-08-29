import { BadRequestException, Controller, Get, Inject, Param, Query } from "@nestjs/common";
import { ApiOperation, ApiTags } from "@nestjs/swagger";
import type { InstrumentBarsResponse, InstrumentIntelligenceDetail } from "@kunlun/shared-types";
import { InstrumentIntelligenceValidationError } from "./instrument-intelligence.query";
import { InstrumentBarsService } from "./instrument-bars.service";
import { InstrumentIntelligenceService } from "./instrument-intelligence.service";

@ApiTags("instrument-intelligence")
@Controller("instrument-intelligence")
export class InstrumentIntelligenceController {
  constructor(
    @Inject(InstrumentIntelligenceService)
    private readonly service: InstrumentIntelligenceService,
    @Inject(InstrumentBarsService)
    private readonly barsService: InstrumentBarsService,
  ) {}

  @Get(":instrumentId/bars")
  @ApiOperation({
    summary: "Query point-in-time daily RAW bars for research-only instrument display",
  })
  async bars(
    @Param("instrumentId") instrumentId: string,
    @Query() query: Record<string, unknown>,
  ): Promise<InstrumentBarsResponse> {
    try {
      return await this.barsService.bars(instrumentId, query);
    } catch (error) {
      if (error instanceof InstrumentIntelligenceValidationError) {
        throw new BadRequestException(error.message);
      }
      throw error;
    }
  }

  @Get(":instrumentId")
  @ApiOperation({
    summary: "Query one point-in-time research-only instrument Intelligence detail",
  })
  async detail(
    @Param("instrumentId") instrumentId: string,
    @Query() query: Record<string, unknown>,
  ): Promise<InstrumentIntelligenceDetail> {
    try {
      return await this.service.detail(instrumentId, query);
    } catch (error) {
      if (error instanceof InstrumentIntelligenceValidationError) {
        throw new BadRequestException(error.message);
      }
      throw error;
    }
  }
}
