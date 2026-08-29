import { Controller, Get, Header } from "@nestjs/common";
import { ApiExcludeEndpoint } from "@nestjs/swagger";
import { apiMetrics } from "./metrics";
import { PublicRoute } from "./modules/auth/public-route.decorator";

@Controller("metrics")
export class MetricsController {
  @Get()
  @PublicRoute()
  @ApiExcludeEndpoint()
  @Header("content-type", "text/plain; version=0.0.4; charset=utf-8")
  metrics(): string {
    return apiMetrics.render();
  }
}
