import { BadRequestException, Controller, Get, Inject, Query } from "@nestjs/common";
import { ApiOperation, ApiTags } from "@nestjs/swagger";
import type { PreciousMetalsTerminalSnapshot } from "@kunlun/shared-types";
import { PreciousMetalsValidationError } from "./precious-metals.query";
import { PreciousMetalsService } from "./precious-metals.service";

@ApiTags("precious-metals")
@Controller("precious-metals")
export class PreciousMetalsController {
  constructor(@Inject(PreciousMetalsService) private readonly service: PreciousMetalsService) {}

  @Get("terminal")
  @ApiOperation({
    summary: "Query the point-in-time exchange-listed precious-metals funds terminal",
  })
  async terminal(@Query() query: Record<string, unknown>): Promise<PreciousMetalsTerminalSnapshot> {
    try {
      return await this.service.terminal(query);
    } catch (error) {
      if (error instanceof PreciousMetalsValidationError) {
        throw new BadRequestException(error.message);
      }
      throw error;
    }
  }
}
