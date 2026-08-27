import { Body, Controller, Get, Inject, Param, Post } from "@nestjs/common";
import { WatchlistAlertsService } from "./watchlist-alerts.service";

@Controller("watchlist-alerts")
export class WatchlistAlertsController {
  constructor(
    @Inject(WatchlistAlertsService) private readonly service: WatchlistAlertsService,
  ) {}

  @Get()
  workspace() {
    return this.service.workspace();
  }

  @Post("rules")
  createRule(@Body() body: unknown) {
    return this.service.createRule(body);
  }

  @Post("rules/:ruleId/toggle")
  toggleRule(@Param("ruleId") ruleId: string, @Body() body: unknown) {
    return this.service.toggleRule(ruleId, body);
  }

  @Post("preview")
  preview(@Body() body: unknown) {
    return this.service.preview(body);
  }

  @Post("evaluate")
  evaluate(@Body() body: unknown) {
    return this.service.evaluate(body);
  }
}
