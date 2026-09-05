import {
  ForbiddenException,
  Inject,
  Injectable,
  Optional,
  ServiceUnavailableException,
} from "@nestjs/common";
import type { MarketCoverageResponse } from "@kunlun/shared-types";
import type { DataQualityRecord, EvidenceRecord } from "./quality-record";
import type { QualityRepository } from "./quality-repository";
import { validateEvidenceId, validateQualityQuery } from "./quality-filters";
import { AllowAllAuthorizer, type DataQualityAuthorizer } from "./data-quality.authorizer";
import {
  MARKET_COVERAGE_CLOCK,
  MARKET_COVERAGE_READ_MODEL,
  QUALITY_AUTHORIZER,
  QUALITY_REPOSITORY,
} from "./data-quality.tokens";
import {
  parseMarketCoverageQuery,
  SystemMarketCoverageClock,
  type MarketCoverageClock,
} from "./market-coverage.query";
import {
  UnavailableMarketCoverageReadModel,
  type MarketCoverageReadModel,
} from "./market-coverage.read-model";

/**
 * Reads persisted quality events through a repository port and validates every
 * filter at the boundary. Repository failures propagate; authorization failures
 * become a controlled forbidden response.
 */
@Injectable()
export class DataQualityService {
  constructor(
    @Inject(QUALITY_REPOSITORY) private readonly repository: QualityRepository,
    @Inject(QUALITY_AUTHORIZER)
    private readonly authorizer: DataQualityAuthorizer = new AllowAllAuthorizer(),
    @Optional()
    @Inject(MARKET_COVERAGE_READ_MODEL)
    private readonly marketCoverage: MarketCoverageReadModel = new UnavailableMarketCoverageReadModel(),
    @Optional()
    @Inject(MARKET_COVERAGE_CLOCK)
    private readonly marketCoverageClock: MarketCoverageClock = new SystemMarketCoverageClock(),
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

  async coverage(input: unknown): Promise<MarketCoverageResponse> {
    await this.assertAuthorized();
    const now = this.marketCoverageClock.now();
    const filters = parseMarketCoverageQuery(input, now);
    const asOf = now.toISOString();
    try {
      const result = await this.marketCoverage.query(filters, asOf);
      return {
        schemaVersion: "market-data-coverage-v1",
        scope: "DAILY_RAW_SUPPORTED_SOURCES",
        meaning: "OBSERVED_ONLY",
        window: {
          dateFrom: filters.dateFrom,
          dateTo: filters.dateTo,
          asOf,
        },
        rows: result.rows,
        truncated: result.truncated,
      };
    } catch {
      throw new ServiceUnavailableException("行情覆盖暂不可用");
    }
  }

  private async assertAuthorized(): Promise<void> {
    if (!(await this.authorizer.canAccess())) {
      throw new ForbiddenException("无权访问数据质量");
    }
  }
}
