import { ApiProperty, ApiPropertyOptional } from "@nestjs/swagger";
import { IsNotEmpty, IsOptional, IsString } from "class-validator";

/** Query boundary for one instrument/source's observed daily-bar dates. */
export class MarketCoverageDaysQueryDto {
  @ApiProperty({ example: "600519.SH" })
  @IsString()
  @IsNotEmpty()
  unifiedCode!: string;

  @ApiProperty({ example: "akshare-tencent" })
  @IsString()
  @IsNotEmpty()
  source!: string;

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
}
