import { BadRequestException } from "@nestjs/common";

export interface ParsedLimitPoolQuery {
  mode: "CURRENT" | "HISTORICAL";
  asOf: string;
  algorithmVersion: string | undefined;
  ladderAlgorithmVersion: string | undefined;
  limitRuleVersion: string | undefined;
  materializerVersion: string | undefined;
}

const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?(?:Z|[+-]\d{2}:\d{2})$/;
const VERSION = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/;
const ALLOWED_FIELDS = new Set([
  "mode",
  "asOf",
  "algorithmVersion",
  "ladderAlgorithmVersion",
  "limitRuleVersion",
  "materializerVersion",
]);

function singleString(value: unknown, field: string): string | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "string" || value === "") {
    throw new BadRequestException(`${field} must be a non-empty string`);
  }
  return value;
}

function instant(value: string): string {
  if (!RFC3339.test(value)) {
    throw new BadRequestException("asOf must be a strict RFC3339 instant");
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    throw new BadRequestException("asOf must be a valid instant");
  }
  return parsed.toISOString();
}

export function parseLimitPoolQuery(
  raw: Record<string, unknown>,
  now = new Date(),
): ParsedLimitPoolQuery {
  for (const field of Object.keys(raw)) {
    if (!ALLOWED_FIELDS.has(field)) {
      throw new BadRequestException(`unknown query field: ${field}`);
    }
  }

  const modeValue = singleString(raw.mode, "mode") ?? "CURRENT";
  if (modeValue !== "CURRENT" && modeValue !== "HISTORICAL") {
    throw new BadRequestException("mode must be CURRENT or HISTORICAL");
  }

  const rawAsOf = singleString(raw.asOf, "asOf");
  if (modeValue === "HISTORICAL" && rawAsOf === undefined) {
    throw new BadRequestException("asOf is required in HISTORICAL mode");
  }
  if (modeValue === "CURRENT" && rawAsOf !== undefined) {
    throw new BadRequestException("asOf is only accepted in HISTORICAL mode");
  }

  const algorithmVersion = singleString(raw.algorithmVersion, "algorithmVersion");
  if (algorithmVersion !== undefined && !VERSION.test(algorithmVersion)) {
    throw new BadRequestException("algorithmVersion has an invalid format");
  }
  const ladderAlgorithmVersion = singleString(raw.ladderAlgorithmVersion, "ladderAlgorithmVersion");
  if (ladderAlgorithmVersion !== undefined && !VERSION.test(ladderAlgorithmVersion)) {
    throw new BadRequestException("ladderAlgorithmVersion has an invalid format");
  }
  const limitRuleVersion = singleString(raw.limitRuleVersion, "limitRuleVersion");
  if (limitRuleVersion !== undefined && !VERSION.test(limitRuleVersion)) {
    throw new BadRequestException("limitRuleVersion has an invalid format");
  }
  const materializerVersion = singleString(raw.materializerVersion, "materializerVersion");
  if (materializerVersion !== undefined && !VERSION.test(materializerVersion)) {
    throw new BadRequestException("materializerVersion has an invalid format");
  }
  const versions = [
    algorithmVersion,
    ladderAlgorithmVersion,
    limitRuleVersion,
    materializerVersion,
  ];
  const suppliedVersionCount = versions.filter((value) => value !== undefined).length;
  if (suppliedVersionCount !== 0 && suppliedVersionCount !== versions.length) {
    throw new BadRequestException("limit-pool version vector must be complete");
  }

  return {
    mode: modeValue,
    asOf: rawAsOf === undefined ? now.toISOString() : instant(rawAsOf),
    algorithmVersion,
    ladderAlgorithmVersion,
    limitRuleVersion,
    materializerVersion,
  };
}
