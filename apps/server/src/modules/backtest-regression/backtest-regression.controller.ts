import { BadRequestException, Controller, Get, Inject, Param, Query } from "@nestjs/common";
import { ApiExtraModels, ApiOperation, ApiTags } from "@nestjs/swagger";
import type {
  BacktestRegressionArtifact,
  BacktestRegressionComparison,
  BacktestRegressionRunSummary,
} from "@kunlun/shared-types";
import { BacktestRegressionComparisonQueryDto } from "./backtest-regression.dto";
import { BacktestRegressionService } from "./backtest-regression.service";
import { BacktestRegressionValidationError } from "./backtest-regression.validation";

@ApiTags("backtest-regression")
@ApiExtraModels(BacktestRegressionComparisonQueryDto)
@Controller("backtest/regressions")
export class BacktestRegressionController {
  constructor(
    @Inject(BacktestRegressionService) private readonly service: BacktestRegressionService,
  ) {}

  @Get()
  @ApiOperation({ summary: "List read-only backtest regression run summaries" })
  async list(): Promise<BacktestRegressionRunSummary[]> {
    try {
      return await this.service.list();
    } catch (error) {
      if (error instanceof BacktestRegressionValidationError)
        throw new BadRequestException(error.message);
      throw error;
    }
  }

  @Get(":runId")
  @ApiOperation({ summary: "Read one immutable backtest regression artifact" })
  async get(@Param("runId") runId: string): Promise<BacktestRegressionArtifact> {
    try {
      return await this.service.get(runId);
    } catch (error) {
      if (error instanceof BacktestRegressionValidationError)
        throw new BadRequestException(error.message);
      throw error;
    }
  }

  @Get(":runId/comparison")
  @ApiOperation({ summary: "Compare one run with an approved baseline" })
  async comparison(
    @Param("runId") runId: string,
    @Query() query: BacktestRegressionComparisonQueryDto,
  ): Promise<BacktestRegressionComparison> {
    try {
      return await this.service.comparison(runId, query.baselineId);
    } catch (error) {
      if (error instanceof BacktestRegressionValidationError)
        throw new BadRequestException(error.message);
      throw error;
    }
  }
}
