import { Module } from "@nestjs/common";
import { HttpRankingEngineClient } from "./ranking-engine.client";
import { RankingTerminalController } from "./ranking-terminal.controller";
import { RankingTerminalService } from "./ranking-terminal.service";
import { RANKING_ENGINE_CLIENT } from "./ranking-terminal.tokens";

@Module({
  controllers: [RankingTerminalController],
  providers: [
    RankingTerminalService,
    {
      provide: RANKING_ENGINE_CLIENT,
      useFactory: () =>
        new HttpRankingEngineClient(
          process.env["QUANT_ENGINE_URL"] ?? "http://127.0.0.1:8081",
          Number(process.env["QUANT_ENGINE_TIMEOUT_MS"] ?? "5000"),
        ),
    },
  ],
})
export class RankingTerminalModule {}
