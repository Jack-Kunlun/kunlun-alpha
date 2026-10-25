import { Body, Controller, Get, Inject, Post } from "@nestjs/common";
import { ApiOperation, ApiTags } from "@nestjs/swagger";
import { PaperTerminalService } from "./paper-terminal.service";

@ApiTags("paper")
@Controller("paper")
export class PaperTerminalController {
  constructor(@Inject(PaperTerminalService) private readonly service: PaperTerminalService) {}

  @Get("workspace")
  @ApiOperation({ summary: "Read the simulation-only paper workspace" })
  workspace() {
    return this.service.workspace();
  }

  @Post("accounts")
  @ApiOperation({ summary: "Create one local simulation-only paper account" })
  createAccount(@Body() body: unknown) {
    return this.service.createAccount(body);
  }

  @Post("previews")
  @ApiOperation({ summary: "Preview a manual paper allocation without writing an order or ledger" })
  preview(@Body() body: unknown) {
    return this.service.preview(body);
  }

  @Post("simulations")
  @ApiOperation({ summary: "Run a signal-to-fill paper simulation" })
  simulate(@Body() body: unknown) {
    return this.service.simulate(body);
  }
}
