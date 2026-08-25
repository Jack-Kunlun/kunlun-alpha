import { Module } from "@nestjs/common";
import { Pool } from "pg";
import { DenyAllClaimReviewAuthorizer } from "./claim-review-authorizer";
import { ClaimReviewController } from "./claim-review.controller";
import type { ClaimReviewRepository } from "./claim-review-repository";
import { ClaimReviewService, SystemClaimReviewClock } from "./claim-review.service";
import { ClaimCandidateMaterializer } from "./claim-candidate-materializer";
import { CLAIM_CANDIDATE_PROJECTION_STORE, CLAIM_REVIEW_AUTHORIZER, CLAIM_REVIEW_CLOCK, CLAIM_REVIEW_REPOSITORY } from "./claim-review.tokens";
import { PostgresClaimReviewRepository } from "./postgres-claim-review.repository";

function buildRepository(): ClaimReviewRepository {
  const dsn = process.env["CLAIM_REVIEW_POSTGRES_DSN"];
  if (!dsn) throw new Error("CLAIM_REVIEW_POSTGRES_DSN is required for claim review");
  return new PostgresClaimReviewRepository(new Pool({ connectionString: dsn }));
}

@Module({ controllers: [ClaimReviewController], providers: [{ provide: CLAIM_REVIEW_REPOSITORY, useFactory: buildRepository }, { provide: CLAIM_CANDIDATE_PROJECTION_STORE, useExisting: CLAIM_REVIEW_REPOSITORY }, { provide: CLAIM_REVIEW_AUTHORIZER, useClass: DenyAllClaimReviewAuthorizer }, { provide: CLAIM_REVIEW_CLOCK, useClass: SystemClaimReviewClock }, ClaimCandidateMaterializer, ClaimReviewService], exports: [ClaimReviewService, ClaimCandidateMaterializer] })
export class ClaimReviewModule {}
