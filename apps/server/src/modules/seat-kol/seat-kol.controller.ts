import { BadRequestException, Controller, Get, Inject, Query } from "@nestjs/common";
import { ApiOperation, ApiTags } from "@nestjs/swagger";
import type { SeatKolWorkbenchSnapshot } from "@kunlun/shared-types";
import { SeatKolWorkbenchService } from "./seat-kol.service";
import { SeatKolValidationError } from "./seat-kol-validation";

@ApiTags("seat-kol")
@Controller("seat-kol")
export class SeatKolWorkbenchController {
  constructor(@Inject(SeatKolWorkbenchService) private readonly service: SeatKolWorkbenchService) {}

  @Get("workbench")
  @ApiOperation({ summary: "Query the point-in-time Seat and KOL research workbench" })
  async workbench(@Query() query: Record<string, unknown>): Promise<SeatKolWorkbenchSnapshot[]> {
    try {
      return await this.service.workbench(query);
    } catch (error) {
      if (error instanceof SeatKolValidationError) throw new BadRequestException(error.message);
      throw error;
    }
  }
}
