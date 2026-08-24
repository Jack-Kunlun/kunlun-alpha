import { BadRequestException, Controller, Get, Inject, Query } from "@nestjs/common";
import { ApiOperation, ApiTags } from "@nestjs/swagger";
import type { HotTopicSnapshot, MarketEvent } from "@kunlun/shared-types";
import { EventIntelligenceService } from "./event-intelligence.service";
import { EventIntelligenceValidationError } from "./event-intelligence-validation";

@ApiTags("event-intelligence")
@Controller("event-intelligence")
export class EventIntelligenceController {
  constructor(
    @Inject(EventIntelligenceService) private readonly service: EventIntelligenceService,
  ) {}

  @Get("events")
  @ApiOperation({ summary: "Query validated MarketEvent records" })
  async events(@Query() query: Record<string, unknown>): Promise<MarketEvent[]> {
    return this.withValidation(() => this.service.events(query));
  }

  @Get("hot-topics")
  @ApiOperation({ summary: "Query latest point-in-time HotTopic snapshots" })
  async hotTopics(@Query() query: Record<string, unknown>): Promise<HotTopicSnapshot[]> {
    return this.withValidation(() => this.service.hotTopics(query));
  }

  private async withValidation<T>(operation: () => Promise<T>): Promise<T> {
    try {
      return await operation();
    } catch (error) {
      if (error instanceof EventIntelligenceValidationError) {
        throw new BadRequestException(error.message);
      }
      throw error;
    }
  }
}
