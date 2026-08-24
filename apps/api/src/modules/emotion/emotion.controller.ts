import { BadRequestException, Controller, Get, Query } from "@nestjs/common";
import { ApiOperation, ApiTags } from "@nestjs/swagger";
import type { MarketEmotionSnapshot, SectorRotationEvent } from "./emotion-snapshot";
import { EmotionValidationError } from "./emotion-query";
import type { EmotionService } from "./emotion.service";

@ApiTags("emotion")
@Controller("emotion")
export class EmotionController {
  constructor(private readonly service: EmotionService) {}

  @Get("snapshots")
  @ApiOperation({ summary: "Replay persisted emotion snapshots for a trading day" })
  async snapshots(@Query() query: Record<string, unknown>): Promise<MarketEmotionSnapshot[]> {
    return this.withValidation(() => this.service.snapshots(query));
  }

  @Get("rotation-events")
  @ApiOperation({ summary: "Replay persisted sector-rotation events" })
  async rotationEvents(@Query() query: Record<string, unknown>): Promise<SectorRotationEvent[]> {
    return this.withValidation(() => this.service.rotationEvents(query));
  }

  @Get("versions")
  @ApiOperation({ summary: "Distinct persisted emotion and rotation algorithm versions" })
  async versions(): Promise<string[]> {
    return this.service.versions();
  }

  private async withValidation<T>(operation: () => Promise<T>): Promise<T> {
    try {
      return await operation();
    } catch (error) {
      if (error instanceof EmotionValidationError) {
        throw new BadRequestException(error.message);
      }
      throw error;
    }
  }
}
