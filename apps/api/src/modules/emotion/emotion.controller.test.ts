import { BadRequestException } from "@nestjs/common";
import { describe, expect, it } from "vitest";
import { EmotionController } from "./emotion.controller";
import { InMemoryEmotionRepository } from "./in-memory-emotion.repository";
import { EmotionService } from "./emotion.service";

function controller(): EmotionController {
  return new EmotionController(new EmotionService(new InMemoryEmotionRepository()));
}

describe("EmotionController", () => {
  it("maps invalid replay filters to 400", async () => {
    await expect(controller().snapshots({ date: "not-a-date" })).rejects.toThrow(
      BadRequestException,
    );
  });

  it("returns repository-backed empty arrays for a valid unknown date", async () => {
    await expect(controller().snapshots({ date: "2026-08-13" })).resolves.toEqual([]);
  });
});
