import { Controller, Get } from "@nestjs/common";
import { ApiOperation, ApiTags } from "@nestjs/swagger";
import type { HealthStatus } from "@kunlun/shared-types";
import { PublicRoute } from "./modules/auth/public-route.decorator";
import { APP_VERSION } from "./app-version";

@ApiTags("health")
@Controller()
export class AppController {
  @Get()
  @PublicRoute()
  @ApiOperation({ summary: "API root redirect" })
  root(): { message: string } {
    return { message: "昆仑智策 API — see /health for status" };
  }

  @Get("health")
  @PublicRoute()
  @ApiOperation({ summary: "Service health check" })
  health(): HealthStatus {
    return {
      status: "ok",
      timestamp: new Date().toISOString(),
      version: APP_VERSION,
    };
  }
}
