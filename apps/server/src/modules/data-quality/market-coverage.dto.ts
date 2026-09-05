import { ApiPropertyOptional } from "@nestjs/swagger";
import { IsOptional, IsString } from "class-validator";

/** Query boundary for the observed market-coverage read model. */
export class MarketCoverageQueryDto {
  @ApiPropertyOptional({ example: "2026-08-13" })
  @IsOptional()
  @IsString()
  date?: string;

  @ApiPropertyOptional({ example: "2026-08-01" })
  @IsOptional()
  @IsString()
  dateFrom?: string;

  @ApiPropertyOptional({ example: "2026-08-31" })
  @IsOptional()
  @IsString()
  dateTo?: string;

  @ApiPropertyOptional({ example: "akshare-tencent" })
  @IsOptional()
  @IsString()
  source?: string;

  @ApiPropertyOptional({ example: "600519.SH" })
  @IsOptional()
  @IsString()
  unifiedCode?: string;
}
