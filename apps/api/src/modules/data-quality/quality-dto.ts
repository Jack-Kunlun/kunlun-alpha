import { ApiPropertyOptional } from "@nestjs/swagger";
import { IsOptional, IsString } from "class-validator";

/**
 * Data-quality query DTO. The global ValidationPipe rejects unknown fields
 * (forbidNonWhitelisted), while the service applies strict format validation
 * (suffix-form code, legal dates, path-traversal rejection).
 */
export class QualityQueryDto {
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

  @ApiPropertyOptional({ example: "provider-a" })
  @IsOptional()
  @IsString()
  source?: string;

  @ApiPropertyOptional({ example: "600519.SH" })
  @IsOptional()
  @IsString()
  unifiedCode?: string;

  @ApiPropertyOptional({ example: "SOURCE_CONFLICT" })
  @IsOptional()
  @IsString()
  kind?: string;
}
