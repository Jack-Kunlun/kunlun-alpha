import { Body, Controller, Get, Inject, Param, Post } from "@nestjs/common";
import { WatchlistAlertsService } from "./watchlist-alerts.service";
import { WatchlistAlertsEvaluationRunner } from "./watchlist-alerts.evaluation-runner";

@Controller("watchlist-alerts")
export class WatchlistAlertsController {
  constructor(
    @Inject(WatchlistAlertsService) private readonly service: WatchlistAlertsService,
    @Inject(WatchlistAlertsEvaluationRunner)
    private readonly evaluationRunner: WatchlistAlertsEvaluationRunner,
  ) {}

  @Get()
  workspace() {
    return this.service.workspace();
  }

  @Get("notifications")
  notifications() {
    return this.service.notificationCenter();
  }

  @Post("notifications/read-all")
  readAllNotifications() {
    return this.service.readAllNotifications();
  }

  @Post("notifications/:notificationId/read")
  readNotification(@Param("notificationId") notificationId: string) {
    return this.service.readNotification(notificationId);
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

  @Post("evaluate-latest")
  evaluateLatest() {
    return this.evaluationRunner.runOnce();
  }
}
