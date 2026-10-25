import { Module } from "@nestjs/common";
import { HttpPaperEngineClient } from "./paper-engine.client";
import { PaperTerminalController } from "./paper-terminal.controller";
import { PaperTerminalService } from "./paper-terminal.service";
import {
  PAPER_ENGINE_CLIENT,
  PAPER_TERMINAL_ACCOUNT_ONLY,
  PAPER_CONTROLLED_BUY_ENABLED,
} from "./paper-terminal.tokens";

@Module({
  controllers: [PaperTerminalController],
  providers: [
    PaperTerminalService,
    {
      provide: PAPER_CONTROLLED_BUY_ENABLED,
      useFactory: () => process.env["PAPER_TERMINAL_CONTROLLED_BUY_ENABLED"] === "true",
    },
    {
      provide: PAPER_TERMINAL_ACCOUNT_ONLY,
      useFactory: () => process.env["PAPER_TERMINAL_ACCOUNT_ONLY"] === "true",
    },
    {
      provide: PAPER_ENGINE_CLIENT,
      useFactory: () =>
        new HttpPaperEngineClient(
          process.env["PAPER_ENGINE_URL"] ?? "http://127.0.0.1:8081",
          Number(process.env["PAPER_ENGINE_TIMEOUT_MS"] ?? "5000"),
          process.env["PAPER_TERMINAL_CONTROLLED_BUY_ENABLED"] === "true",
        ),
    },
  ],
})
export class PaperTerminalModule {}
