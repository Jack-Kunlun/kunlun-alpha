import { Module } from "@nestjs/common";
import { MarketDataStatusController } from "./market-data-status.controller";
import { MarketDataStatusReader } from "./market-data-status.reader";

function reader(): MarketDataStatusReader {
  const symbols = process.env["DASHBOARD_DAILY_SYMBOLS"]?.split(",") ?? [];
  if (
    symbols.length > 100 ||
    new Set(symbols).size !== symbols.length ||
    symbols.some((symbol) => !/^\d{6}\.(SH|SZ)$/.test(symbol))
  )
    throw new Error("Invalid daily sample configuration");
  const provider = process.env["MARKET_DATA_STATUS_PROVIDER"] ?? "akshare";
  if (provider !== "akshare" && provider !== "tushare")
    throw new Error("Invalid status provider configuration");
  return new MarketDataStatusReader(
    process.env["MARKET_DATA_STATUS_PUBLIC_ROOT"],
    symbols,
    provider,
  );
}

@Module({
  controllers: [MarketDataStatusController],
  providers: [{ provide: MarketDataStatusReader, useFactory: reader }],
})
export class MarketDataStatusModule {}
