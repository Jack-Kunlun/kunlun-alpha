import { Module } from "@nestjs/common";
import {
  ClickHouseEmotionRepository,
  type ClickHouseEmotionConfig,
} from "./clickhouse-emotion.repository";
import { AllowAllEmotionAuthorizer } from "./emotion-authorizer";
import { EmotionController } from "./emotion.controller";
import type { EmotionRepository } from "./emotion-repository";
import { EmotionService } from "./emotion.service";
import { EMOTION_AUTHORIZER, EMOTION_REPOSITORY } from "./emotion.tokens";

function buildRepository(): EmotionRepository {
  const url = process.env["EMOTION_CLICKHOUSE_URL"];
  if (!url) {
    throw new Error("EMOTION_CLICKHOUSE_URL is required for persisted emotion replay");
  }
  const config: ClickHouseEmotionConfig = {
    url,
    database: process.env["EMOTION_CLICKHOUSE_DATABASE"] ?? "kunlun",
    user: process.env["EMOTION_CLICKHOUSE_USER"] ?? "default",
  };
  const password = process.env["EMOTION_CLICKHOUSE_PASSWORD"];
  if (password !== undefined) config.password = password;
  return new ClickHouseEmotionRepository(config);
}

@Module({
  controllers: [EmotionController],
  providers: [
    { provide: EMOTION_REPOSITORY, useFactory: buildRepository },
    { provide: EMOTION_AUTHORIZER, useClass: AllowAllEmotionAuthorizer },
    EmotionService,
  ],
  exports: [EmotionService],
})
export class EmotionModule {}
