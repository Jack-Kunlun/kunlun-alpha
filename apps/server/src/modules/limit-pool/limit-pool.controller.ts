import type { LimitPoolTerminalSnapshot } from "@kunlun/shared-types";
import { Controller, Get, Inject, Query, Req } from "@nestjs/common";
import { parseLimitPoolQuery } from "./limit-pool-query";
import { LimitPoolService } from "./limit-pool.service";

@Controller("limit-pool")
export class LimitPoolController {
  constructor(@Inject(LimitPoolService) private readonly service: LimitPoolService) {}

  @Get()
  getSnapshot(
    @Req() request: unknown,
    @Query() query: Record<string, unknown>,
  ): Promise<LimitPoolTerminalSnapshot> {
    return this.service.getSnapshot(request, parseLimitPoolQuery(query));
  }
}
