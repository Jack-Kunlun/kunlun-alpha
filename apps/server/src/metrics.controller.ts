import { Controller, Get, Header } from "@nestjs/common";
import { ApiExcludeEndpoint } from "@nestjs/swagger";
import { apiMetrics } from "./metrics";

@Controller("metrics")
export class MetricsController {
  @Get()
  @ApiExcludeEndpoint()
  @Header("content-type", "text/plain; version=0.0.4; charset=utf-8")
  metrics(): string {
    return apiMetrics.render();
  }
}
