import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  canonicalJson,
  parseCanonicalDecimal,
  parseBacktestRegressionArtifact,
  parseBacktestRegressionBaseline,
  parseBacktestRegressionComparison,
  sha256Json,
} from "./index";

describe("backtest regression contracts", () => {
  it("exports fail-closed runtime parsers", () => {
    expect(() => parseBacktestRegressionArtifact({ unknown: true })).toThrow();
    expect(() => parseBacktestRegressionBaseline({ unknown: true })).toThrow();
  });

  it("uses strict canonical JSON and rejects duplicate or noncanonical Decimal input", () => {
    expect(canonicalJson({ b: "1", a: ["2"] })).toBe('{"a":["2"],"b":"1"}\n');
    expect(sha256Json({ value: "1" })).toMatch(/^[0-9a-f]{64}$/);
    expect(() => canonicalJson({ value: 1.5 })).toThrow();
    expect(() => parseBacktestRegressionArtifact('{"a":1,"a":2}\n')).toThrow();
  });

  it("rejects unsupported diff categories and accepts a closed comparison shape", () => {
    expect(() =>
      parseBacktestRegressionComparison({
        baselineSha256: "a".repeat(64),
        candidateSha256: "a".repeat(64),
        status: "DRIFTED",
        categoryCounts: { RESULT: 1 },
        diffs: [{ category: "UNKNOWN", pointer: "/x", status: "REPLACED", baselineValue: null, candidateValue: null }],
        diffLines: ["RESULT REPLACED /x"],
      }),
    ).toThrow();
  });

  it.each(["-0", "1.00", "0.0", "1e0", "+1", "01"])(
    "rejects noncanonical Decimal spelling %s",
    (value) => {
      expect(() => parseCanonicalDecimal(value)).toThrow();
    },
  );

  it.each(["-0.5", "0", "0.5", "1", "1.5", "-10.05"])(
    "accepts canonical Decimal spelling %s",
    (value) => {
      expect(parseCanonicalDecimal(value)).toBe(value);
    },
  );

  it("rejects semantically inconsistent comparison payloads", () => {
    const valid = {
      baselineSha256: "a".repeat(64),
      candidateSha256: "b".repeat(64),
      status: "DRIFTED" as const,
      categoryCounts: {
        SCHEMA: 0,
        MANIFEST_INPUT: 0,
        ALGORITHM_CONFIG: 0,
        DEPENDENCY_TOOLCHAIN: 0,
        RESULT: 1,
      },
      diffs: [
        {
          category: "RESULT" as const,
          pointer: "/results/x",
          status: "REPLACED" as const,
          baselineValue: 1,
          candidateValue: 2,
        },
      ],
      diffLines: ["RESULT REPLACED /results/x"],
    };
    expect(parseBacktestRegressionComparison(valid).categoryCounts.RESULT).toBe(1);
    expect(() => parseBacktestRegressionComparison({ ...valid, status: "MATCHED" })).toThrow();
    expect(() => parseBacktestRegressionComparison({ ...valid, diffLines: ["untrusted text"] })).toThrow();
    expect(() => parseBacktestRegressionComparison({ ...valid, diffs: [] })).toThrow();
    expect(() => parseBacktestRegressionComparison({ ...valid, categoryCounts: { ...valid.categoryCounts, RESULT: 0 } })).toThrow();
    expect(() => parseBacktestRegressionComparison({ ...valid, categoryCounts: { ...valid.categoryCounts, EXTRA: 0 } })).toThrow();
    expect(() => parseBacktestRegressionComparison({ ...valid, diffs: [{ ...valid.diffs[0], pointer: "/results/~2" }] })).toThrow();
  });

  it("rejects unsorted and duplicate diff identities", () => {
    const base = {
      baselineSha256: "a".repeat(64),
      candidateSha256: "b".repeat(64),
      status: "DRIFTED" as const,
      categoryCounts: {
        SCHEMA: 0,
        MANIFEST_INPUT: 0,
        ALGORITHM_CONFIG: 0,
        DEPENDENCY_TOOLCHAIN: 0,
        RESULT: 2,
      },
      diffs: [
        { category: "RESULT" as const, pointer: "/results/Z", status: "REPLACED" as const, baselineValue: 1, candidateValue: 2 },
        { category: "RESULT" as const, pointer: "/results/a", status: "REPLACED" as const, baselineValue: 1, candidateValue: 2 },
      ],
      diffLines: ["RESULT REPLACED /results/Z", "RESULT REPLACED /results/a"],
    };
    expect(parseBacktestRegressionComparison(base).diffLines).toHaveLength(2);
    expect(() => parseBacktestRegressionComparison({ ...base, diffs: [...base.diffs].reverse(), diffLines: [...base.diffLines].reverse() })).toThrow();
    expect(() => parseBacktestRegressionComparison({ ...base, diffs: [...base.diffs, base.diffs[0]], diffLines: [...base.diffLines, base.diffLines[0]], categoryCounts: { ...base.categoryCounts, RESULT: 3 } })).toThrow();
  });

  it("binds toolchain claims and accepts the shared cross-runtime parity fixture", () => {
    const moduleUrl = (import.meta as unknown as { url: string }).url;
    const RuntimeURL = (globalThis as unknown as {
      URL: new (input: string, base: string) => unknown;
    }).URL;
    const filePath = (relativePath: string): string =>
      new RuntimeURL(relativePath, moduleUrl) as string;
    const baseline = JSON.parse(
      readFileSync(
        filePath(
          "../../../../services/quant-engine/fixtures/regression/p5-core-chain.baseline.json",
        ),
        "utf8",
      ),
    ) as { expectedArtifact: Record<string, unknown> };
    expect(() => parseBacktestRegressionArtifact(baseline.expectedArtifact)).not.toThrow();
    const parity = JSON.parse(
      readFileSync(
        filePath("../../fixtures/backtest-regression-comparison-parity.json"),
        "utf8",
      ),
    ) as Record<string, unknown>;
    expect(parseBacktestRegressionComparison(parity).diffLines).toEqual(parity.diffLines);

    const object = (value: unknown): Record<string, unknown> => {
      if (value === null || typeof value !== "object" || Array.isArray(value)) {
        throw new TypeError("expected object");
      }
      return value as Record<string, unknown>;
    };
    for (const forge of [
      (artifact: Record<string, unknown>) => {
        object(object(artifact.provenance).toolchain).uvLockSha256 = "c".repeat(64);
      },
      (artifact: Record<string, unknown>) => {
        object(object(artifact.provenance).toolchain).evidenceSha256 = "d".repeat(64);
      },
      (artifact: Record<string, unknown>) => {
        const config = object(artifact.provenance).config;
        if (!Array.isArray(config)) throw new TypeError("expected config array");
        config.push(config[0]);
      },
    ]) {
      const forged = JSON.parse(JSON.stringify(baseline.expectedArtifact)) as Record<string, unknown>;
      forge(forged);
      expect(() => parseBacktestRegressionArtifact(forged)).toThrow();
    }
  });
});
