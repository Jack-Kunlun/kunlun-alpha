import {
  ForbiddenException,
  Inject,
  Injectable,
  NotFoundException,
  ServiceUnavailableException,
} from "@nestjs/common";
import type {
  BacktestRegressionArtifact,
  BacktestRegressionComparison,
  BacktestRegressionRunSummary,
} from "@kunlun/shared-types";
import {
  BACKTEST_REGRESSION_AUTHORIZER,
  BACKTEST_REGRESSION_REPOSITORY,
} from "./backtest-regression.tokens";
import type {
  BacktestRegressionAuthorizer,
  BacktestRegressionRepository,
} from "./backtest-regression.types";
import {
  assertSafeId,
  parseBacktestRegressionArtifact,
  parseBacktestRegressionBaseline,
  BacktestRegressionUnavailableError,
  BacktestRegressionValidationError,
} from "./backtest-regression.validation";
import { compareBacktestArtifacts } from "./backtest-regression.comparison";

@Injectable()
export class BacktestRegressionService {
  constructor(
    @Inject(BACKTEST_REGRESSION_REPOSITORY)
    private readonly repository: BacktestRegressionRepository,
    @Inject(BACKTEST_REGRESSION_AUTHORIZER)
    private readonly authorizer: BacktestRegressionAuthorizer,
  ) {}

  private async authorize(): Promise<void> {
    if (!(await this.authorizer.canAccess())) throw new ForbiddenException("无权访问回测回归制品");
  }

  private artifactOrUnavailable(value: unknown): BacktestRegressionArtifact {
    try {
      return parseBacktestRegressionArtifact(value);
    } catch (error) {
      if (error instanceof BacktestRegressionValidationError) {
        throw new ServiceUnavailableException("回测回归制品契约无效");
      }
      throw new ServiceUnavailableException("回测回归制品损坏");
    }
  }

  private async approvedComparison(
    candidate: BacktestRegressionArtifact,
  ): Promise<BacktestRegressionComparison> {
    let baselinePayload;
    try {
      baselinePayload = await this.repository.getBaseline(candidate.suiteId);
    } catch {
      throw new ServiceUnavailableException("回测基线不可用");
    }
    let baseline;
    try {
      baseline = parseBacktestRegressionBaseline(baselinePayload);
      const expected = this.artifactOrUnavailable(baseline.expectedArtifact);
      if (
        baseline.baselineId !== candidate.suiteId ||
        baseline.suiteId !== candidate.suiteId ||
        baseline.expectedArtifactSha256 !== expected.artifactSha256
      ) {
        throw new ServiceUnavailableException("回测基线审批链无效");
      }
      return compareBacktestArtifacts(expected, candidate);
    } catch (error) {
      if (error instanceof ServiceUnavailableException) throw error;
      throw new ServiceUnavailableException("回测基线不可用");
    }
  }

  async list(): Promise<BacktestRegressionRunSummary[]> {
    await this.authorize();
    try {
      const source = this.repository.source();
      const artifacts = await this.repository.list();
      return await Promise.all(
        artifacts.map(async (raw) => {
          const candidate = this.artifactOrUnavailable(raw);
          const comparison = await this.approvedComparison(candidate);
          return this.summary(candidate, comparison, source);
        }),
      );
    } catch (error) {
      if (error instanceof ForbiddenException || error instanceof ServiceUnavailableException)
        throw error;
      throw new ServiceUnavailableException("回测回归制品不可用");
    }
  }

  async get(runId: unknown): Promise<BacktestRegressionArtifact> {
    await this.authorize();
    const safeRunId = assertSafeId(runId, "runId");
    try {
      return this.artifactOrUnavailable(await this.repository.get(safeRunId));
    } catch (error) {
      if (error instanceof ForbiddenException || error instanceof ServiceUnavailableException)
        throw error;
      if (error instanceof BacktestRegressionUnavailableError)
        throw new NotFoundException("回测运行不存在");
      throw new ServiceUnavailableException("回测回归制品不可用");
    }
  }

  async comparison(runId: unknown, baselineId: unknown): Promise<BacktestRegressionComparison> {
    await this.authorize();
    const safeRunId = assertSafeId(runId, "runId");
    const safeBaselineId = assertSafeId(baselineId, "baselineId");
    let candidate: BacktestRegressionArtifact;
    try {
      candidate = this.artifactOrUnavailable(await this.repository.get(safeRunId));
    } catch (error) {
      if (error instanceof BacktestRegressionUnavailableError)
        throw new NotFoundException("回测运行不存在");
      throw error;
    }
    let baselinePayload;
    try {
      baselinePayload = await this.repository.getBaseline(safeBaselineId);
    } catch {
      throw new ServiceUnavailableException("回测基线不可用");
    }
    try {
      const baseline = parseBacktestRegressionBaseline(baselinePayload);
      const expected = this.artifactOrUnavailable(baseline.expectedArtifact);
      if (
        baseline.baselineId !== safeBaselineId ||
        baseline.suiteId !== candidate.suiteId ||
        baseline.expectedArtifactSha256 !== expected.artifactSha256
      ) {
        throw new ServiceUnavailableException("回测基线审批链无效");
      }
      return compareBacktestArtifacts(expected, candidate);
    } catch (error) {
      if (error instanceof ServiceUnavailableException) throw error;
      throw new ServiceUnavailableException("回测基线不可用");
    }
  }

  private summary(
    artifact: BacktestRegressionArtifact,
    comparison: BacktestRegressionComparison,
    source: Pick<BacktestRegressionRunSummary, "availability" | "preview">,
  ): BacktestRegressionRunSummary {
    const times = artifact.inputs.navObservations.map((item) => item.observationTime);
    return {
      schemaVersion: "backtest-regression-summary-v1",
      suiteId: artifact.suiteId,
      runId: artifact.runId,
      fixtureId: artifact.fixtureId,
      status: comparison.status,
      candidateSha256: comparison.candidateSha256,
      baselineSha256: comparison.baselineSha256,
      dataStart: times[0] ?? "",
      dataEnd: times[times.length - 1] ?? "",
      availability: source.availability,
      evidenceIntegrityConfidence: artifact.trust.evidenceIntegrityConfidence,
      preview: source.preview,
    };
  }
}
