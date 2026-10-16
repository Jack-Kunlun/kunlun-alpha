import { Controller, Get, Inject } from "@nestjs/common";
import { ApiOperation, ApiTags } from "@nestjs/swagger";
import type { MarketDataSyncStatus } from "@kunlun/shared-types";
import { MarketDataStatusReader } from "./market-data-status.reader";

@ApiTags("market-data")
@Controller("market-data")
export class MarketDataStatusController {
  constructor(@Inject(MarketDataStatusReader) private readonly reader: MarketDataStatusReader) {}

  @Get("status")
  @ApiOperation({ summary: "Current daily ingestion task state, independent of market data dates" })
  status(): Promise<MarketDataSyncStatus> {
    return this.reader.read();
  }
}
