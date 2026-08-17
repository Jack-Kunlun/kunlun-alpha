import { ForbiddenException, Inject, Injectable } from "@nestjs/common";
import type { DataQualityRecord, EvidenceRecord } from "./quality-record";
import type { QualityRepository } from "./quality-repository";
import { validateEvidenceId, validateQualityQuery } from "./quality-filters";
import { AllowAllAuthorizer, type DataQualityAuthorizer } from "./data-quality.authorizer";
import { QUALITY_AUTHORIZER, QUALITY_REPOSITORY } from "./data-quality.tokens";

/**
 * Reads persisted quality events through a repository port and validates every
 * filter at the boundary. Repository failures propagate; authorization failures
 * become a controlled forbidden response.
 */
@Injectable()
export class DataQualityService {
  constructor(
    @Inject(QUALITY_REPOSITORY) private readonly repository: QualityRepository,
    @Inject(QUALITY_AUTHORIZER) private readonly authorizer: DataQualityAuthorizer = new AllowAllAuthorizer(),
  ) {}

  async query(input: unknown): Promise<DataQualityRecord[]> {
    await this.assertAuthorized();
    const filters = validateQualityQuery(input);
    return this.repository.query(filters);
  }

  async getEvidence(id: unknown): Promise<EvidenceRecord | null> {
    await this.assertAuthorized();
    const evidenceId = validateEvidenceId(id);
    return this.repository.getEvidence(evidenceId);
  }

  private async assertAuthorized(): Promise<void> {
    if (!(await this.authorizer.canAccess())) {
      throw new ForbiddenException("无权访问数据质量");
    }
  }
}
