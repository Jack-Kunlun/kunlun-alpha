import { BadRequestException, Body, Controller, Inject, Post } from "@nestjs/common";
import type { KolClaimReview } from "@kunlun/shared-types";
import { ClaimReviewService } from "./claim-review.service";
import { ClaimReviewValidationError } from "./claim-review-validation";

@Controller("claim-review")
export class ClaimReviewController {
  constructor(@Inject(ClaimReviewService) private readonly service: ClaimReviewService) {}

  @Post()
  async submit(@Body() body: unknown): Promise<KolClaimReview> {
    try { return await this.service.submit(body); } catch (error) { if (error instanceof ClaimReviewValidationError) throw new BadRequestException(error.message); throw error; }
  }
}
