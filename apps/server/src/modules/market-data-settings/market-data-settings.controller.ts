import { Controller, Get, Header, Inject, Post, Req } from "@nestjs/common";
import { InternalServiceRoute } from "../auth/internal-service-route.decorator";
import type { AuthenticatedRequest } from "../auth/auth.request";
import { MarketDataSettingsService } from "./market-data-settings.service";

@Controller("market-data")
export class MarketDataSettingsController {
  constructor(
    @Inject(MarketDataSettingsService) private readonly service: MarketDataSettingsService,
  ) {}

  @Get("settings")
  @Header("Cache-Control", "no-store")
  async get(@Req() request: AuthenticatedRequest) {
    const session = request.authSession;
    return this.service.getBrowserSettings(session?.userId ?? "", session?.roles ?? []);
  }

  @Post("settings")
  @Header("Cache-Control", "no-store")
  async update(@Req() request: AuthenticatedRequest) {
    const session = request.authSession;
    return this.service.updateBrowserSettings(
      session?.userId ?? "",
      session?.roles ?? [],
      request.body,
    );
  }
}

@Controller("internal/market-data")
export class MarketDataSettingsInternalController {
  constructor(
    @Inject(MarketDataSettingsService) private readonly service: MarketDataSettingsService,
  ) {}

  @Get("settings")
  @Header("Cache-Control", "no-store")
  @InternalServiceRoute("market-data-settings")
  async get() {
    return this.service.getWorkerSettings();
  }
}
