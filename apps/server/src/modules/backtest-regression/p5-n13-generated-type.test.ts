import type {
  BacktestRegressionArtifact,
  BacktestRegressionBaseline,
} from "@kunlun/shared-types";
import { describe, expect, it } from "vitest";

type Equal<Left, Right> =
  (<Value>() => Value extends Left ? 1 : 2) extends
  (<Value>() => Value extends Right ? 1 : 2)
    ? true
    : false;
type Expect<Value extends true> = Value;
type HasStringIndex<Value> = string extends keyof Value ? true : false;

type ArtifactHasNoBroadIndexSignature = Expect<Equal<HasStringIndex<BacktestRegressionArtifact>, false>>;
type BaselineUsesExactArtifact = Expect<Equal<BacktestRegressionBaseline["expectedArtifact"], BacktestRegressionArtifact>>;

export const generatedTypeAssertions: [
  ArtifactHasNoBroadIndexSignature,
  BaselineUsesExactArtifact,
] = [true, true];

describe("generated backtest regression types", () => {
  it("exposes the exact artifact and baseline relationship", () => {
    expect(generatedTypeAssertions).toEqual([true, true]);
  });
});
