const VERSION_PATTERN = /^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$/;
const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9:._-]*$/;
const STRATEGY_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const FEATURE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const DECIMAL_PATTERN = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;
const RFC3339_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/;

export type StrategySignalContract = Readonly<{
  schemaVersion: "signal-v1";
  signalId: string;
  strategyId: string;
  strategyVersion: string;
  algorithmVersion: string;
  entityId: string;
  decisionTime: string;
  dataCutoffTime: string;
  direction: "LONG" | "SHORT" | "NEUTRAL";
  score: string;
  confidence: string;
  horizonSessions: number;
  rationale: string;
  inputSnapshotId: string;
  inputSnapshotVersion: string;
  evidenceIds: readonly string[];
  isExecutable: false;
  executionCapability: "NONE";
}>;

type IntegerParameterSpec = Readonly<{
  name: string;
  valueType: "INTEGER";
  required: boolean;
  description: string;
  defaultValue: number | null | undefined;
  minimum: number | null | undefined;
  maximum: number | null | undefined;
}>;

type DecimalParameterSpec = Readonly<{
  name: string;
  valueType: "DECIMAL";
  required: boolean;
  description: string;
  defaultValue: string | null | undefined;
  minimum: string | null | undefined;
  maximum: string | null | undefined;
}>;

type BooleanParameterSpec = Readonly<{
  name: string;
  valueType: "BOOLEAN";
  required: boolean;
  description: string;
  defaultValue: boolean | null | undefined;
}>;

type StringParameterSpec = Readonly<{
  name: string;
  valueType: "STRING";
  required: boolean;
  description: string;
  defaultValue: string | null | undefined;
}>;

export type StrategyParameterSpecContract =
  IntegerParameterSpec | DecimalParameterSpec | BooleanParameterSpec | StringParameterSpec;

export type StrategyDescriptorContract = Readonly<{
  schemaVersion: "strategy-descriptor-v1";
  strategyId: string;
  strategyVersion: string;
  algorithmVersion: string;
  sdkVersion: string;
  lifecycleVersion: string;
  description: string;
  requiredFeatures: readonly string[];
  parameterSpecs: readonly StrategyParameterSpecContract[];
  lifecycleHooks: readonly ["initialize", "onDecision", "finalize"];
  signalSchemaVersion: "signal-v1";
  executionCapability: "NONE";
}>;

type JsonRecord = Record<string, unknown>;

function fail(message: string): never {
  throw new TypeError(message);
}

function asRecord(value: unknown, field: string): JsonRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return fail(`${field} must be an object`);
  }
  return value as JsonRecord;
}

function assertExactKeys(
  value: JsonRecord,
  required: readonly string[],
  optional: readonly string[] = [],
): void {
  const allowed = new Set([...required, ...optional]);
  for (const key of required) {
    if (!Object.hasOwn(value, key)) fail(`${key} is required`);
  }
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) fail(`${key} is not allowed`);
  }
}

function readString(
  value: JsonRecord,
  key: string,
  options: { pattern?: RegExp; max?: number } = {},
): string {
  const candidate = value[key];
  if (typeof candidate !== "string" || candidate.length === 0) {
    return fail(`${key} must be a non-empty string`);
  }
  if (options.max !== undefined && candidate.length > options.max) {
    return fail(`${key} exceeds maximum length`);
  }
  if (options.pattern !== undefined && !options.pattern.test(candidate)) {
    return fail(`${key} has invalid format`);
  }
  return candidate;
}

function readVersion(value: JsonRecord, key: string): string {
  return readString(value, key, { pattern: VERSION_PATTERN });
}

function readRfc3339(value: JsonRecord, key: string): string {
  const candidate = readString(value, key, { pattern: RFC3339_PATTERN });
  if (!Number.isFinite(Date.parse(candidate))) fail(`${key} must be a valid RFC3339 timestamp`);
  return candidate;
}

function readBoolean(value: JsonRecord, key: string): boolean {
  if (typeof value[key] !== "boolean") fail(`${key} must be boolean`);
  return value[key];
}

function readInteger(value: JsonRecord, key: string, minimum: number, maximum: number): number {
  const candidate = value[key];
  if (
    !Number.isInteger(candidate) ||
    (candidate as number) < minimum ||
    (candidate as number) > maximum
  ) {
    return fail(`${key} must be an integer between ${minimum} and ${maximum}`);
  }
  return candidate as number;
}

type NormalizedDecimal = Readonly<{
  negative: boolean;
  integer: string;
  fraction: string;
}>;

function normalizeDecimal(value: string): NormalizedDecimal {
  const negativeInput = value.startsWith("-");
  const unsigned = negativeInput ? value.slice(1) : value;
  const [rawInteger = "0", rawFraction = ""] = unsigned.split(".");
  const integer = rawInteger.replace(/^0+(?=\d)/, "");
  const fraction = rawFraction.replace(/0+$/, "");
  const isZero = integer === "0" && fraction.length === 0;
  return { negative: negativeInput && !isZero, integer, fraction };
}

function compareDecimalMagnitude(left: NormalizedDecimal, right: NormalizedDecimal): number {
  if (left.integer.length !== right.integer.length) {
    return left.integer.length < right.integer.length ? -1 : 1;
  }
  if (left.integer !== right.integer) return left.integer < right.integer ? -1 : 1;
  const width = Math.max(left.fraction.length, right.fraction.length);
  const leftFraction = left.fraction.padEnd(width, "0");
  const rightFraction = right.fraction.padEnd(width, "0");
  if (leftFraction === rightFraction) return 0;
  return leftFraction < rightFraction ? -1 : 1;
}

function compareDecimal(leftValue: string, rightValue: string): number {
  const left = normalizeDecimal(leftValue);
  const right = normalizeDecimal(rightValue);
  if (left.negative !== right.negative) return left.negative ? -1 : 1;
  const magnitude = compareDecimalMagnitude(left, right);
  return left.negative ? -magnitude : magnitude;
}

function readDecimal(value: JsonRecord, key: string, minimum?: string, maximum?: string): string {
  const candidate = readString(value, key, { pattern: DECIMAL_PATTERN });
  if (minimum !== undefined && compareDecimal(candidate, minimum) < 0) {
    fail(`${key} is below minimum`);
  }
  if (maximum !== undefined && compareDecimal(candidate, maximum) > 0) {
    fail(`${key} exceeds maximum`);
  }
  return candidate;
}

function readSortedUniqueStrings(
  candidate: unknown,
  field: string,
  pattern?: RegExp,
  maxLength?: number,
): readonly string[] {
  if (!Array.isArray(candidate) || candidate.length === 0) {
    return fail(`${field} must be a non-empty array`);
  }
  const values = candidate.map((item) => {
    if (
      typeof item !== "string" ||
      item.length === 0 ||
      (maxLength !== undefined && item.length > maxLength) ||
      (pattern !== undefined && !pattern.test(item))
    ) {
      return fail(`${field} must contain valid non-empty strings`);
    }
    return item;
  });
  if (new Set(values).size !== values.length) fail(`${field} must not contain duplicates`);
  if (values.some((item, index) => item !== [...values].sort()[index])) {
    fail(`${field} must be deterministically sorted`);
  }
  return Object.freeze(values);
}

function readOptionalInteger(value: JsonRecord, key: string): number | null | undefined {
  if (!Object.hasOwn(value, key)) return undefined;
  if (value[key] === null) return null;
  if (!Number.isInteger(value[key])) fail(`${key} must be an exact INTEGER or null`);
  return value[key] as number;
}

function readOptionalDecimal(value: JsonRecord, key: string): string | null | undefined {
  if (!Object.hasOwn(value, key)) return undefined;
  if (value[key] === null) return null;
  return readDecimal(value, key);
}

function readOptionalBoolean(value: JsonRecord, key: string): boolean | null | undefined {
  if (!Object.hasOwn(value, key)) return undefined;
  if (value[key] === null) return null;
  return readBoolean(value, key);
}

function readOptionalString(value: JsonRecord, key: string): string | null | undefined {
  if (!Object.hasOwn(value, key)) return undefined;
  if (value[key] === null) return null;
  return readString(value, key);
}

function compareIntegerBounds(
  name: string,
  defaultValue: number | null | undefined,
  minimum: number | null | undefined,
  maximum: number | null | undefined,
): void {
  if (
    minimum !== null &&
    minimum !== undefined &&
    maximum !== null &&
    maximum !== undefined &&
    minimum > maximum
  ) {
    fail(`${name} minimum must not exceed maximum`);
  }
  if (
    defaultValue !== null &&
    defaultValue !== undefined &&
    minimum !== null &&
    minimum !== undefined &&
    defaultValue < minimum
  ) {
    fail(`${name} default is below minimum`);
  }
  if (
    defaultValue !== null &&
    defaultValue !== undefined &&
    maximum !== null &&
    maximum !== undefined &&
    defaultValue > maximum
  ) {
    fail(`${name} default exceeds maximum`);
  }
}

function compareDecimalBounds(
  name: string,
  defaultValue: string | null | undefined,
  minimum: string | null | undefined,
  maximum: string | null | undefined,
): void {
  if (
    minimum !== null &&
    minimum !== undefined &&
    maximum !== null &&
    maximum !== undefined &&
    compareDecimal(minimum, maximum) > 0
  ) {
    fail(`${name} minimum must not exceed maximum`);
  }
  if (
    defaultValue !== null &&
    defaultValue !== undefined &&
    minimum !== null &&
    minimum !== undefined &&
    compareDecimal(defaultValue, minimum) < 0
  ) {
    fail(`${name} default is below minimum`);
  }
  if (
    defaultValue !== null &&
    defaultValue !== undefined &&
    maximum !== null &&
    maximum !== undefined &&
    compareDecimal(defaultValue, maximum) > 0
  ) {
    fail(`${name} default exceeds maximum`);
  }
}

function parseParameterSpec(input: unknown): StrategyParameterSpecContract {
  const value = asRecord(input, "parameterSpec");
  const valueType = value["valueType"];
  const commonRequired = ["name", "valueType", "required", "description"] as const;
  const name = readString(value, "name", { max: 128 });
  const required = readBoolean(value, "required");
  const description = readString(value, "description", { max: 1000 });

  if (valueType === "INTEGER") {
    assertExactKeys(value, commonRequired, ["defaultValue", "minimum", "maximum"]);
    const defaultValue = readOptionalInteger(value, "defaultValue");
    const minimum = readOptionalInteger(value, "minimum");
    const maximum = readOptionalInteger(value, "maximum");
    compareIntegerBounds(name, defaultValue, minimum, maximum);
    return Object.freeze({
      name,
      valueType,
      required,
      description,
      defaultValue,
      minimum,
      maximum,
    });
  }
  if (valueType === "DECIMAL") {
    assertExactKeys(value, commonRequired, ["defaultValue", "minimum", "maximum"]);
    const defaultValue = readOptionalDecimal(value, "defaultValue");
    const minimum = readOptionalDecimal(value, "minimum");
    const maximum = readOptionalDecimal(value, "maximum");
    compareDecimalBounds(name, defaultValue, minimum, maximum);
    return Object.freeze({
      name,
      valueType,
      required,
      description,
      defaultValue,
      minimum,
      maximum,
    });
  }
  if (valueType === "BOOLEAN") {
    assertExactKeys(value, commonRequired, ["defaultValue"]);
    const defaultValue = readOptionalBoolean(value, "defaultValue");
    return Object.freeze({ name, valueType, required, description, defaultValue });
  }
  if (valueType === "STRING") {
    assertExactKeys(value, commonRequired, ["defaultValue"]);
    const defaultValue = readOptionalString(value, "defaultValue");
    return Object.freeze({ name, valueType, required, description, defaultValue });
  }
  return fail("valueType must be INTEGER, DECIMAL, BOOLEAN, or STRING");
}

export function parseStrategySignal(input: unknown): StrategySignalContract {
  const value = asRecord(input, "Signal");
  const keys = [
    "schemaVersion",
    "signalId",
    "strategyId",
    "strategyVersion",
    "algorithmVersion",
    "entityId",
    "decisionTime",
    "dataCutoffTime",
    "direction",
    "score",
    "confidence",
    "horizonSessions",
    "rationale",
    "inputSnapshotId",
    "inputSnapshotVersion",
    "evidenceIds",
    "isExecutable",
    "executionCapability",
  ] as const;
  assertExactKeys(value, keys);
  if (value["schemaVersion"] !== "signal-v1") fail("schemaVersion must be signal-v1");
  if (value["isExecutable"] !== false) fail("isExecutable must be false");
  if (value["executionCapability"] !== "NONE") fail("executionCapability must be NONE");
  const direction = value["direction"];
  if (direction !== "LONG" && direction !== "SHORT" && direction !== "NEUTRAL") {
    fail("direction must be LONG, SHORT, or NEUTRAL");
  }
  const decisionTime = readRfc3339(value, "decisionTime");
  const dataCutoffTime = readRfc3339(value, "dataCutoffTime");
  if (Date.parse(dataCutoffTime) > Date.parse(decisionTime)) {
    fail("dataCutoffTime must not exceed decisionTime");
  }

  return Object.freeze({
    schemaVersion: "signal-v1",
    signalId: readString(value, "signalId", { pattern: ID_PATTERN, max: 256 }),
    strategyId: readString(value, "strategyId", { pattern: STRATEGY_ID_PATTERN, max: 128 }),
    strategyVersion: readVersion(value, "strategyVersion"),
    algorithmVersion: readVersion(value, "algorithmVersion"),
    entityId: readString(value, "entityId", { max: 128 }),
    decisionTime,
    dataCutoffTime,
    direction,
    score: readDecimal(value, "score", "-1", "1"),
    confidence: readDecimal(value, "confidence", "0", "1"),
    horizonSessions: readInteger(value, "horizonSessions", 1, 10_000),
    rationale: readString(value, "rationale", { max: 4000 }),
    inputSnapshotId: readString(value, "inputSnapshotId", { max: 256 }),
    inputSnapshotVersion: readVersion(value, "inputSnapshotVersion"),
    evidenceIds: readSortedUniqueStrings(value["evidenceIds"], "evidenceIds", undefined, 512),
    isExecutable: false,
    executionCapability: "NONE",
  });
}

export function parseStrategyDescriptor(input: unknown): StrategyDescriptorContract {
  const value = asRecord(input, "StrategyDescriptor");
  const keys = [
    "schemaVersion",
    "strategyId",
    "strategyVersion",
    "algorithmVersion",
    "sdkVersion",
    "lifecycleVersion",
    "description",
    "requiredFeatures",
    "parameterSpecs",
    "lifecycleHooks",
    "signalSchemaVersion",
    "executionCapability",
  ] as const;
  assertExactKeys(value, keys);
  if (value["schemaVersion"] !== "strategy-descriptor-v1") {
    fail("schemaVersion must be strategy-descriptor-v1");
  }
  if (value["signalSchemaVersion"] !== "signal-v1") {
    fail("signalSchemaVersion must be signal-v1");
  }
  if (value["executionCapability"] !== "NONE") fail("executionCapability must be NONE");
  const hooks = value["lifecycleHooks"];
  if (
    !Array.isArray(hooks) ||
    hooks.length !== 3 ||
    hooks[0] !== "initialize" ||
    hooks[1] !== "onDecision" ||
    hooks[2] !== "finalize"
  ) {
    fail("lifecycleHooks must be initialize/onDecision/finalize");
  }
  if (!Array.isArray(value["parameterSpecs"]) || value["parameterSpecs"].length === 0) {
    fail("parameterSpecs must be a non-empty array");
  }
  const parameterSpecs = value["parameterSpecs"].map(parseParameterSpec);
  const names = parameterSpecs.map((item) => item.name);
  if (new Set(names).size !== names.length) fail("parameterSpecs must not contain duplicates");
  if (names.some((item, index) => item !== [...names].sort()[index])) {
    fail("parameterSpecs must be deterministically sorted");
  }

  const lifecycleHooks = Object.freeze(["initialize", "onDecision", "finalize"] as const);
  return Object.freeze({
    schemaVersion: "strategy-descriptor-v1",
    strategyId: readString(value, "strategyId", { pattern: STRATEGY_ID_PATTERN, max: 128 }),
    strategyVersion: readVersion(value, "strategyVersion"),
    algorithmVersion: readVersion(value, "algorithmVersion"),
    sdkVersion: readVersion(value, "sdkVersion"),
    lifecycleVersion: readVersion(value, "lifecycleVersion"),
    description: readString(value, "description", { max: 2000 }),
    requiredFeatures: readSortedUniqueStrings(
      value["requiredFeatures"],
      "requiredFeatures",
      FEATURE_PATTERN,
      256,
    ),
    parameterSpecs: Object.freeze(parameterSpecs),
    lifecycleHooks,
    signalSchemaVersion: "signal-v1",
    executionCapability: "NONE",
  });
}
