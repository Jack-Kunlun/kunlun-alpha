import { BadRequestException, ForbiddenException } from "@nestjs/common";
import { describe, expect, it } from "vitest";
import { ClaimReviewController } from "./claim-review.controller";
import { InMemoryClaimReviewRepository } from "./in-memory-claim-review.repository";
import { ClaimReviewService } from "./claim-review.service";

describe("ClaimReviewController authorization boundary", () => {
  it("returns forbidden without a trusted reviewer principal", async () => {
    const controller = new ClaimReviewController(
      new ClaimReviewService(new InMemoryClaimReviewRepository()),
    );
    await expect(controller.submit({})).rejects.toBeInstanceOf(ForbiddenException);
  });

  it("accepts a trusted injected principal through the service port, not a client header", async () => {
    const service = new ClaimReviewService(
      new InMemoryClaimReviewRepository(),
      { currentReviewerRef: async () => "trusted-internal-reviewer" },
    );
    await expect(new ClaimReviewController(service).submit({})).rejects.toBeInstanceOf(BadRequestException);
  });
});
