import { Module, type Type } from "@nestjs/common";
import { NestFactory } from "@nestjs/core";
import { describe, expect, it } from "vitest";

import { EmotionController } from "./emotion/emotion.controller";
import { EmotionService } from "./emotion/emotion.service";
import { EventFeedbackController } from "./event-feedback/event-feedback.controller";
import { EventFeedbackService } from "./event-feedback/event-feedback.service";
import { EventIntelligenceController } from "./event-intelligence/event-intelligence.controller";
import { EventIntelligenceService } from "./event-intelligence/event-intelligence.service";
import { SeatKolWorkbenchController } from "./seat-kol/seat-kol.controller";
import { SeatKolWorkbenchService } from "./seat-kol/seat-kol.service";

const emotionService = {};
const eventFeedbackService = {};
const eventIntelligenceService = {};
const seatKolWorkbenchService = {};

@Module({
  controllers: [EmotionController],
  providers: [{ provide: EmotionService, useValue: emotionService }],
})
class EmotionControllerRuntimeTestModule {}

@Module({
  controllers: [EventFeedbackController],
  providers: [{ provide: EventFeedbackService, useValue: eventFeedbackService }],
})
class EventFeedbackControllerRuntimeTestModule {}

@Module({
  controllers: [EventIntelligenceController],
  providers: [{ provide: EventIntelligenceService, useValue: eventIntelligenceService }],
})
class EventIntelligenceControllerRuntimeTestModule {}

@Module({
  controllers: [SeatKolWorkbenchController],
  providers: [{ provide: SeatKolWorkbenchService, useValue: seatKolWorkbenchService }],
})
class SeatKolWorkbenchControllerRuntimeTestModule {}

async function expectRuntimeInjection(
  moduleType: Type<unknown>,
  controllerType: Type<unknown>,
  expectedService: unknown,
): Promise<void> {
  const application = await NestFactory.createApplicationContext(moduleType, { logger: false });
  try {
    const controller = application.get(controllerType) as unknown as { service: unknown };
    expect(controller.service).toBe(expectedService);
  } finally {
    await application.close();
  }
}

describe("controller runtime injection", () => {
  it("injects EmotionService", async () => {
    await expectRuntimeInjection(
      EmotionControllerRuntimeTestModule,
      EmotionController,
      emotionService,
    );
  });

  it("injects EventFeedbackService", async () => {
    await expectRuntimeInjection(
      EventFeedbackControllerRuntimeTestModule,
      EventFeedbackController,
      eventFeedbackService,
    );
  });

  it("injects EventIntelligenceService", async () => {
    await expectRuntimeInjection(
      EventIntelligenceControllerRuntimeTestModule,
      EventIntelligenceController,
      eventIntelligenceService,
    );
  });

  it("injects SeatKolWorkbenchService", async () => {
    await expectRuntimeInjection(
      SeatKolWorkbenchControllerRuntimeTestModule,
      SeatKolWorkbenchController,
      seatKolWorkbenchService,
    );
  });
});
