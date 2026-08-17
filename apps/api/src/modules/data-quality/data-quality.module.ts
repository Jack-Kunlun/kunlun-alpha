import { Module } from "@nestjs/common";
import { Pool } from "pg";
import { DataQualityController } from "./data-quality.controller";
import { DataQualityService } from "./data-quality.service";
import { PostgresQualityRepository } from "./postgres-quality.repository";
import { AllowAllAuthorizer } from "./data-quality.authorizer";
import { QUALITY_AUTHORIZER, QUALITY_REPOSITORY } from "./data-quality.tokens";
import type { QualityRepository } from "./quality-repository";

function buildRepository(): QualityRepository {
  const dsn = process.env["DATA_QUALITY_POSTGRES_DSN"];
  if (!dsn) {
    throw new Error("DATA_QUALITY_POSTGRES_DSN is required for the data-quality repository");
  }
  return new PostgresQualityRepository(new Pool({ connectionString: dsn }));
}

@Module({
  controllers: [DataQualityController],
  providers: [
    { provide: QUALITY_REPOSITORY, useFactory: buildRepository },
    { provide: QUALITY_AUTHORIZER, useClass: AllowAllAuthorizer },
    DataQualityService,
  ],
  exports: [DataQualityService],
})
export class DataQualityModule {}
