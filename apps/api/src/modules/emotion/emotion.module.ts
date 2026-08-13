import { Module } from "@nestjs/common";
import { EmotionController } from "./emotion.controller";
import { EMOTION_SNAPSHOTS, EmotionService } from "./emotion.service";

@Module({
  controllers: [EmotionController],
  providers: [EmotionService, { provide: EMOTION_SNAPSHOTS, useValue: [] }],
  exports: [EmotionService],
})
export class EmotionModule {}
