import { sha256Json, type JsonObject } from "./backtest-regression.validation";
import type {
  BacktestRegressionArtifact,
  BacktestRegressionComparison,
  BacktestRegressionDiff,
} from "@kunlun/shared-types";
import { parseBacktestRegressionComparison } from "@kunlun/contracts/backtest-regression";

const CATEGORY_ORDER = [
  "SCHEMA",
  "MANIFEST_INPUT",
  "ALGORITHM_CONFIG",
  "DEPENDENCY_TOOLCHAIN",
  "RESULT",
] as const;
type DiffCategory = (typeof CATEGORY_ORDER)[number];

function compareAscii(left: string, right: string): number {
  const length = Math.min(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    if (left.charCodeAt(index) !== right.charCodeAt(index)) {
      return left.charCodeAt(index) - right.charCodeAt(index);
    }
  }
  return left.length - right.length;
}

function category(pointer: string): DiffCategory {
  const first = pointer.split("/")[1] ?? "";
  if (first === "schemaVersion" || first === "canonicalizationVersion") return "SCHEMA";
  if (["manifest", "inputs", "suiteId", "runId", "fixtureId"].includes(first))
    return "MANIFEST_INPUT";
  if (first === "provenance") {
    const second = pointer.split("/")[2] ?? "";
    return second === "dependencies" || second === "toolchain"
      ? "DEPENDENCY_TOOLCHAIN"
      : "ALGORITHM_CONFIG";
  }
  if (first === "versions" || first === "trust") return "ALGORITHM_CONFIG";
  if (first === "results") return "RESULT";
  return "SCHEMA";
}

function escapeSegment(value: string): string {
  return value.replaceAll("~", "~0").replaceAll("/", "~1");
}

function diffTree(baseline: unknown, candidate: unknown, pointer = ""): BacktestRegressionDiff[] {
  if (
    baseline !== null &&
    candidate !== null &&
    typeof baseline === "object" &&
    typeof candidate === "object"
  ) {
    if (Array.isArray(baseline) && Array.isArray(candidate)) {
      const result: BacktestRegressionDiff[] = [];
      for (let index = 0; index < Math.max(baseline.length, candidate.length); index += 1) {
        const child = `${pointer}/${index}`;
        if (index >= baseline.length)
          result.push({
            category: category(child),
            pointer: child,
            status: "ADDED",
            baselineValue: null,
            candidateValue: candidate[index],
          });
        else if (index >= candidate.length)
          result.push({
            category: category(child),
            pointer: child,
            status: "REMOVED",
            baselineValue: baseline[index],
            candidateValue: null,
          });
        else result.push(...diffTree(baseline[index], candidate[index], child));
      }
      return result;
    }
    if (!Array.isArray(baseline) && !Array.isArray(candidate)) {
      const left = baseline as JsonObject;
      const right = candidate as JsonObject;
      const result: BacktestRegressionDiff[] = [];
      for (const key of Object.keys({ ...left, ...right }).sort(compareAscii)) {
        if (pointer === "" && key === "artifactSha256") continue;
        const child = `${pointer}/${escapeSegment(key)}`;
        if (!(key in left))
          result.push({
            category: category(child),
            pointer: child,
            status: "ADDED",
            baselineValue: null,
            candidateValue: right[key],
          });
        else if (!(key in right))
          result.push({
            category: category(child),
            pointer: child,
            status: "REMOVED",
            baselineValue: left[key],
            candidateValue: null,
          });
        else result.push(...diffTree(left[key], right[key], child));
      }
      return result;
    }
  }
  return Object.is(baseline, candidate)
    ? []
    : [
        {
          category: category(pointer),
          pointer: pointer || "/",
          status: "REPLACED",
          baselineValue: baseline,
          candidateValue: candidate,
        },
      ];
}

export function compareBacktestArtifacts(
  baseline: BacktestRegressionArtifact,
  candidate: BacktestRegressionArtifact,
): BacktestRegressionComparison {
  const diffs = diffTree(baseline, candidate).sort((left, right) => {
    const categoryDelta =
      CATEGORY_ORDER.indexOf(left["category"] as DiffCategory) -
      CATEGORY_ORDER.indexOf(right["category"] as DiffCategory);
    return categoryDelta || compareAscii(String(left["pointer"]), String(right["pointer"]));
  });
  const categoryCounts: BacktestRegressionComparison["categoryCounts"] = {
    SCHEMA: diffs.filter((item) => item.category === "SCHEMA").length,
    MANIFEST_INPUT: diffs.filter((item) => item.category === "MANIFEST_INPUT").length,
    ALGORITHM_CONFIG: diffs.filter((item) => item.category === "ALGORITHM_CONFIG").length,
    DEPENDENCY_TOOLCHAIN: diffs.filter((item) => item.category === "DEPENDENCY_TOOLCHAIN").length,
    RESULT: diffs.filter((item) => item.category === "RESULT").length,
  };
  return parseBacktestRegressionComparison({
    baselineSha256: baseline.artifactSha256,
    candidateSha256: candidate.artifactSha256,
    status: diffs.length === 0 ? "MATCHED" : "DRIFTED",
    categoryCounts,
    diffs,
    diffLines: diffs.map((item) => `${item.category} ${item.status} ${item.pointer}`),
  });
}

export function verifyArtifactDigest(artifact: JsonObject): void {
  const { artifactSha256, ...withoutDigest } = artifact;
  if (typeof artifactSha256 !== "string" || sha256Json(withoutDigest) !== artifactSha256) {
    throw new Error("artifact digest mismatch");
  }
}
