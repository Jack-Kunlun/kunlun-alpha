import { ApiProperty } from "@nestjs/swagger";
import { IsString } from "class-validator";

export class BacktestRegressionComparisonQueryDto {
  @ApiProperty({ example: "p5-core-chain" })
  @IsString()
  baselineId!: string;
}
