import { describe, expect, it } from "vitest";
import { combineReplayResults, replayQuery } from "./use-market-regime";

describe("market-regime query", () => {
  it("builds only API filter names", () => {
    expect(
      replayQuery({
        date: "2026-08-13",
        algorithmVersion: "emotion_score_v1",
        sectorId: "sector-gold",
      }),
    ).toEqual({
      date: "2026-08-13",
      algorithmVersion: "emotion_score_v1",
      sectorId: "sector-gold",
    });
  });

  it("combines two empty persisted regions into an empty state", () => {
    expect(
      combineReplayResults(
        { status: "empty", data: [], error: null },
        { status: "empty", data: [], error: null },
      ).status,
    ).toBe("empty");
  });

  it("forbidden takes precedence over a partial success", () => {
    expect(
      combineReplayResults(
        { status: "success", data: [], error: null },
        { status: "forbidden", data: null, error: new Error("denied") },
      ).status,
    ).toBe("forbidden");
  });
});
