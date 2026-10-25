import { Body, Controller, Get, HttpCode, Inject, Post } from "@nestjs/common";
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

  @Post("risk-previews")
  @HttpCode(200)
  @ApiOperation({
    summary: "Check an unchanged allocation snapshot without enabling execution or writing state",
  })
  riskPreview(@Body() body: unknown) {
    return this.service.riskPreview(body);
  }

  @Post("simulations")
  @ApiOperation({ summary: "Run a signal-to-fill paper simulation" })
  simulate(@Body() body: unknown) {
    return this.service.simulate(body);
  }

  @Post("buy-simulations")
  @HttpCode(200)
  @ApiOperation({ summary: "Confirm a buy-only paper fill from an unchanged allocation snapshot" })
  buyAllocation(@Body() body: unknown) {
    return this.service.buyAllocation(body);
  }
}
