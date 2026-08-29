import { describe, expect, it } from "vitest";
import {
  instrumentIntelligencePath,
  instrumentIntelligenceQuery,
} from "./use-instrument-intelligence";

describe("instrument intelligence API helpers", () => {
  it("uses the versioned instrument endpoint", () => {
    expect(instrumentIntelligencePath("600519.SH")).toBe("/v1/instrument-intelligence/600519.SH");
    expect(instrumentIntelligenceQuery(null)).toEqual({ mode: "CURRENT" });
  });
});
