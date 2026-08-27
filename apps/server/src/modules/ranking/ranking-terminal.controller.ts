import { Controller, Get, Inject, Query } from "@nestjs/common";
import { ApiOperation, ApiTags } from "@nestjs/swagger";
import { RankingTerminalService } from "./ranking-terminal.service";

@ApiTags("ranking")
@Controller("ranking")
export class RankingTerminalController {
  constructor(@Inject(RankingTerminalService) private readonly service: RankingTerminalService) {}

  @Get("latest")
  @ApiOperation({ summary: "Read the latest published point-in-time ranking snapshot" })
  latest(@Query("asOf") asOf?: string) {
    return this.service.latest(asOf);
  }
}
