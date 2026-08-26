import { BadRequestException } from "@nestjs/common";
import { describe, expect, it } from "vitest";
import { parseLimitPoolQuery } from "./limit-pool-query";

describe("parseLimitPoolQuery", () => {
  it("uses the injected clock for a current snapshot", () => {
    expect(parseLimitPoolQuery({}, new Date("2026-08-26T02:30:00.000Z"))).toEqual({
      mode: "CURRENT",
      asOf: "2026-08-26T02:30:00.000Z",
      algorithmVersion: undefined,
      ladderAlgorithmVersion: undefined,
      limitRuleVersion: undefined,
      materializerVersion: undefined,
    });
  });

  it("requires a strict RFC3339 instant for historical mode", () => {
    expect(parseLimitPoolQuery({ mode: "HISTORICAL", asOf: "2026-08-25T06:45:00.000Z" })).toEqual({
      mode: "HISTORICAL",
      asOf: "2026-08-25T06:45:00.000Z",
      algorithmVersion: undefined,
      ladderAlgorithmVersion: undefined,
      limitRuleVersion: undefined,
      materializerVersion: undefined,
    });
    expect(() => parseLimitPoolQuery({ mode: "HISTORICAL", asOf: "2026-08-25 14:45" })).toThrow(
      BadRequestException,
    );
  });

  it("rejects unknown fields and unsafe algorithm versions", () => {
    expect(() => parseLimitPoolQuery({ date: "2026-08-25" })).toThrow(BadRequestException);
    expect(() => parseLimitPoolQuery({ algorithmVersion: "v1' OR 1=1" })).toThrow(
      BadRequestException,
    );
  });

  it("accepts only an all-or-nothing immutable version vector", () => {
    expect(() => parseLimitPoolQuery({ algorithmVersion: "limit-pool-v2" })).toThrow(
      BadRequestException,
    );
    expect(
      parseLimitPoolQuery({
        algorithmVersion: "limit-pool-v2",
        ladderAlgorithmVersion: "board_ladder_v2",
        limitRuleVersion: "limit_rules_v1",
        materializerVersion: "limit-pool-terminal-materializer-v1",
      }),
    ).toMatchObject({
      algorithmVersion: "limit-pool-v2",
      ladderAlgorithmVersion: "board_ladder_v2",
      limitRuleVersion: "limit_rules_v1",
      materializerVersion: "limit-pool-terminal-materializer-v1",
    });
  });
});
