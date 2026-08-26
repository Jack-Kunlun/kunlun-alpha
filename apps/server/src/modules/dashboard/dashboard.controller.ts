import { BadRequestException, Controller, Get, Inject, Query } from "@nestjs/common";
import { ApiOperation, ApiTags } from "@nestjs/swagger";
import type { MarketOverviewSnapshot } from "@kunlun/shared-types";
import { DashboardValidationError } from "./dashboard-query";
import { DashboardService } from "./dashboard.service";

@ApiTags("dashboard")
@Controller("dashboard")
export class DashboardController {
  constructor(@Inject(DashboardService) private readonly service: DashboardService) {}

  @Get("market-overview")
  @ApiOperation({ summary: "Point-in-time market overview for research and paper decisions" })
  async marketOverview(@Query() query: Record<string, unknown>): Promise<MarketOverviewSnapshot> {
    try {
      return await this.service.marketOverview(query);
    } catch (error) {
      if (error instanceof DashboardValidationError) {
        throw new BadRequestException(error.message);
      }
      throw error;
    }
  }
}
