import { BadRequestException, Body, Controller, Get, Inject, Post, Query } from "@nestjs/common";
import { ApiOperation, ApiTags } from "@nestjs/swagger";
import type { EventFeedback } from "@kunlun/shared-types";
import { EventFeedbackService } from "./event-feedback.service";
import { EventFeedbackValidationError } from "./event-feedback-validation";

@ApiTags("event-feedback")
@Controller("event-feedback")
export class EventFeedbackController {
  constructor(@Inject(EventFeedbackService) private readonly service: EventFeedbackService) {}

  @Post()
  @ApiOperation({ summary: "Append idempotent human feedback for an exact MarketEvent version" })
  async submit(@Body() body: unknown): Promise<EventFeedback> {
    return this.withValidation(() => this.service.submit(body));
  }

  @Get()
  @ApiOperation({ summary: "List authorized event feedback for evaluation curation" })
  async list(@Query() query: Record<string, unknown>): Promise<EventFeedback[]> {
    return this.withValidation(() => this.service.list(query));
  }

  private async withValidation<T>(operation: () => Promise<T>): Promise<T> {
    try {
      return await operation();
    } catch (error) {
      if (error instanceof EventFeedbackValidationError) {
        throw new BadRequestException(error.message);
      }
      throw error;
    }
  }
}
