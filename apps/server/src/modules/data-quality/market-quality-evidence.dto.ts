import { ApiProperty, ApiPropertyOptional } from "@nestjs/swagger";
import { Type } from "class-transformer";
import { IsInt, IsOptional, IsString, Max, Min } from "class-validator";

/** Query boundary for the immutable, sanitized market-quality evidence projection. */
export class MarketQualityEvidenceQueryDto {
  @ApiPropertyOptional({ example: "akshare-tencent" })
  @IsOptional()
  @IsString()
  source?: string;

  @ApiPropertyOptional({ example: "600519.SH" })
  @IsOptional()
  @IsString()
  unifiedCode?: string;

  @ApiPropertyOptional({ enum: ["REJECTED", "FILTERED"] })
  @IsOptional()
  @IsString()
  status?: string;

  @ApiPropertyOptional({ example: "2026-08-01" })
  @IsOptional()
  @IsString()
  start?: string;

  @ApiPropertyOptional({ example: "2026-08-31" })
  @IsOptional()
  @IsString()
  end?: string;

  @ApiPropertyOptional({ pattern: "^[0-9a-f]{64}$" })
  @IsOptional()
  @IsString()
  snapshotId?: string;

  @ApiPropertyOptional({ minimum: 1, maximum: 100, default: 20 })
  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(1)
  @Max(100)
  limit?: number;

  @ApiPropertyOptional({ minimum: 0, maximum: 10000, default: 0 })
  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(0)
  @Max(10_000)
  offset?: number;
}

export class MarketQualityEvidenceDetailQueryDto {
  @ApiProperty({ pattern: "^[0-9a-f]{64}$" })
  @IsString()
  snapshotId!: string;
}
