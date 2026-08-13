import { Controller, Get, Query } from "@nestjs/common";
import { ApiOperation, ApiTags } from "@nestjs/swagger";
import type { EmotionSnapshot } from "./emotion-snapshot";
import type { EmotionService } from "./emotion.service";

@ApiTags("emotion")
@Controller("emotion")
export class EmotionController {
  constructor(private readonly service: EmotionService) {}

  @Get("snapshots")
  @ApiOperation({ summary: "Replay emotion snapshots for a trading day, with algorithm version" })
  snapshots(@Query("date") date: string): EmotionSnapshot[] {
    return this.service.query(date);
  }

  @Get("versions")
  @ApiOperation({ summary: "Distinct algorithm versions available" })
  versions(): string[] {
    return this.service.versions();
  }
}
