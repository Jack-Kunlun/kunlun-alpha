/**
 * Runtime boundary for untrusted seat payloads. Generated interfaces are
 * transport shapes only; callers must validate before using a payload.
 */

export const SEAT_ID_ALGORITHM_VERSION = "seat-id-v1" as const;
export const SEAT_ID_NAMESPACE = "kunlun-seat-id-v1" as const;
export const SEAT_ID_PREFIX = "seat-" as const;

export type ValidationResult = {
  valid: boolean;
  errors: string[];
};

type JsonRecord = Record<string, unknown>;
type ParsedDecimal = {
  negative: boolean;
  unscaled: bigint;
  scale: number;
};
type TextEncoderLike = { encode(input: string): Uint8Array };
type WebCryptoLike = {
  subtle: {
    digest(algorithm: "SHA-256", data: Uint8Array): Promise<ArrayBuffer>;
  };
};
type RuntimeGlobals = {
  TextEncoder: new () => TextEncoderLike;
  crypto?: WebCryptoLike;
};

const SEAT_ID_PATTERN = /^seat-[0-9a-f]{64}$/;
const IDENTITY_KEY_PATTERN = /^[^\s:]+(?::[^\s:]+)+$/;
const INSTRUMENT_ID_PATTERN = /^[0-9]{6}\.(SH|SZ|BJ)$/;
const DECIMAL_PATTERN = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const INSTANT_PATTERN = /T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const SEAT_KINDS = new Set(["BROKER_BRANCH", "INSTITUTION", "UNKNOWN", "OTHER"]);
const ALIAS_TYPES = new Set(["OFFICIAL", "FORMER", "SOURCE", "ALTERNATE"]);

function record(value: unknown): JsonRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonRecord)
    : null;
}

function result(errors: string[]): ValidationResult {
  return { valid: errors.length === 0, errors };
}

function requiredString(payload: JsonRecord, field: string, errors: string[]): string | undefined {
  const value = payload[field];
  if (typeof value !== "string" || value.length === 0) {
    errors.push(`${field} must be a non-empty string`);
    return undefined;
  }
  return value;
}

function optionalString(
  payload: JsonRecord,
  field: string,
  errors: string[],
): string | null | undefined {
  const value = payload[field];
  if (value === null) return null;
  if (typeof value !== "string" || value.length === 0) {
    errors.push(`${field} must be a non-empty string or null`);
    return undefined;
  }
  return value;
}

function validateRevisionChain(payload: JsonRecord, errors: string[]): void {
  const revisionId = requiredString(payload, "revisionId", errors);
  const previousRevisionId = optionalString(payload, "previousRevisionId", errors);
  if (revisionId !== undefined && previousRevisionId === revisionId) {
    errors.push("previousRevisionId must differ from revisionId");
  }
}

function instant(value: unknown, field: string, errors: string[]): number | undefined {
  if (typeof value !== "string" || !INSTANT_PATTERN.test(value)) {
    errors.push(`${field} must be a timezone-aware RFC 3339 instant`);
    return undefined;
  }
  const milliseconds = Date.parse(value);
  if (Number.isNaN(milliseconds)) {
    errors.push(`${field} must be a valid instant`);
    return undefined;
  }
  return milliseconds;
}

function dateOnly(value: unknown, field: string, errors: string[]): void {
  if (
    typeof value !== "string" ||
    !DATE_PATTERN.test(value) ||
    Number.isNaN(Date.parse(`${value}T00:00:00Z`))
  ) {
    errors.push(`${field} must be an ISO date`);
  }
}

function interval(
  payload: JsonRecord,
  fromField: string,
  toField: string,
  errors: string[],
): { from: number | undefined; to: number | undefined } {
  const from = instant(payload[fromField], fromField, errors);
  const rawTo = payload[toField];
  const to = rawTo === null ? undefined : instant(rawTo, toField, errors);
  if (from !== undefined && to !== undefined && to <= from) {
    errors.push(`${toField} must be greater than ${fromField}`);
  }
  return { from, to };
}

function validateSeatId(value: unknown, field: string, errors: string[]): value is string {
  if (typeof value !== "string" || !SEAT_ID_PATTERN.test(value)) {
    errors.push(`${field} must match seat-[0-9a-f]{64}`);
    return false;
  }
  return true;
}

function validateIdentityKey(value: unknown, errors: string[]): value is string {
  if (typeof value !== "string" || value.length === 0) {
    errors.push("identityKey must be a non-empty string");
    return false;
  }
  if (value.includes("\0")) {
    errors.push("identityKey must not contain NUL");
  }
  if (value.normalize("NFC") !== value) {
    errors.push("identityKey must already be Unicode NFC-normalized");
  }
  if (!IDENTITY_KEY_PATTERN.test(value)) {
    errors.push("identityKey must use namespace:opaque segments without whitespace");
  }
  return errors.every((error) => !error.startsWith("identityKey "));
}

export function normalizeIdentityKey(identityKey: string): string {
  const errors: string[] = [];
  if (!validateIdentityKey(identityKey, errors)) {
    throw new Error(errors.join("; "));
  }
  return identityKey;
}

export async function computeSeatId(
  identityKey: string,
  algorithm: string = SEAT_ID_ALGORITHM_VERSION,
): Promise<string> {
  if (algorithm !== SEAT_ID_ALGORITHM_VERSION) {
    throw new Error(`unsupported seatIdAlgorithm: ${algorithm}`);
  }
  const normalized = normalizeIdentityKey(identityKey);
  const runtime = globalThis as unknown as RuntimeGlobals;
  const material = new runtime.TextEncoder().encode(`${SEAT_ID_NAMESPACE}\0${normalized}`);
  const subtle = runtime.crypto?.subtle;
  if (subtle === undefined) {
    throw new Error("Web Crypto SubtleCrypto is required to compute seat ids");
  }
  const digest = await subtle.digest("SHA-256", material);
  return `${SEAT_ID_PREFIX}${Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("")}`;
}

function stringArray(payload: JsonRecord, field: string, errors: string[]): string[] | undefined {
  const value = payload[field];
  if (
    !Array.isArray(value) ||
    value.some((item) => typeof item !== "string" || item.length === 0)
  ) {
    errors.push(`${field} must be a non-empty string array`);
    return undefined;
  }
  const values = value as string[];
  if (values.length === 0) errors.push(`${field} must not be empty`);
  if (new Set(values).size !== values.length) errors.push(`${field} must not contain duplicates`);
  return values;
}

function validateLineage(
  payload: JsonRecord,
  seatId: string | undefined,
  validFrom: number | undefined,
  validTo: number | undefined,
  errors: string[],
): void {
  const value = payload.lineage;
  if (!Array.isArray(value)) {
    errors.push("lineage must be an array");
    return;
  }
  const lineageIds = new Set<string>();
  const lineageRecords = new Set<string>();
  value.forEach((entry, index) => {
    const item = record(entry);
    if (item === null) {
      errors.push(`lineage[${index}] must be an object`);
      return;
    }
    const lineageId = requiredString(item, "lineageId", errors);
    const relation = requiredString(item, "relation", errors);
    const predecessors = stringArray(item, "predecessorSeatIds", errors);
    const successors = stringArray(item, "successorSeatIds", errors);
    const effectiveAt = instant(item.effectiveAt, `lineage[${index}].effectiveAt`, errors);
    requiredString(item, "source", errors);
    requiredString(item, "sourceVersion", errors);
    requiredString(item, "evidenceId", errors);
    requiredString(item, "revisionId", errors);

    predecessors?.forEach((candidate, candidateIndex) => {
      validateSeatId(candidate, `lineage[${index}].predecessorSeatIds[${candidateIndex}]`, errors);
    });
    successors?.forEach((candidate, candidateIndex) => {
      validateSeatId(candidate, `lineage[${index}].successorSeatIds[${candidateIndex}]`, errors);
    });

    if (lineageId !== undefined) {
      if (lineageIds.has(lineageId)) errors.push("lineageId must be unique");
      lineageIds.add(lineageId);
    }
    if (
      lineageId !== undefined &&
      relation !== undefined &&
      predecessors !== undefined &&
      successors !== undefined
    ) {
      const key = JSON.stringify([
        lineageId,
        relation,
        predecessors,
        successors,
        item.effectiveAt,
        item.source,
        item.sourceVersion,
        item.evidenceId,
        item.revisionId,
      ]);
      if (lineageRecords.has(key)) errors.push("lineage records must be unique");
      lineageRecords.add(key);
    }
    if (predecessors !== undefined && successors !== undefined) {
      const predecessorSet = new Set(predecessors);
      if (successors.some((successor) => predecessorSet.has(successor))) {
        errors.push("lineage predecessors and successors must be disjoint");
      }
      if (relation === "MERGE" && (predecessors.length < 2 || successors.length !== 1)) {
        errors.push("MERGE must have at least two predecessors and exactly one successor");
      }
      if (relation === "SPLIT" && (predecessors.length !== 1 || successors.length < 2)) {
        errors.push("SPLIT must have exactly one predecessor and at least two successors");
      }
      if (relation !== "MERGE" && relation !== "SPLIT") {
        errors.push("relation must be MERGE or SPLIT");
      }
      if (seatId !== undefined) {
        if (relation === "MERGE" && !successors.includes(seatId)) {
          errors.push("MERGE profile seatId must be a successor");
        }
        if (relation === "SPLIT" && !predecessors.includes(seatId)) {
          errors.push("SPLIT profile seatId must be a predecessor");
        }
      }
    }
    if (
      (effectiveAt !== undefined && validFrom !== undefined && effectiveAt < validFrom) ||
      (effectiveAt !== undefined && validTo !== undefined && effectiveAt >= validTo)
    ) {
      errors.push("lineage effectiveAt must be inside the profile half-open validity interval");
    }
  });
}

export async function validateSeatProfilePayload(input: unknown): Promise<ValidationResult> {
  const payload = record(input);
  if (payload === null) return result(["payload must be an object"]);
  const errors: string[] = [];
  if (payload.schemaVersion !== "seat-profile-v1")
    errors.push("schemaVersion must be seat-profile-v1");
  if (payload.seatIdAlgorithm !== SEAT_ID_ALGORITHM_VERSION) {
    errors.push("seatIdAlgorithm must be seat-id-v1");
  }
  const seatId = validateSeatId(payload.seatId, "seatId", errors) ? payload.seatId : undefined;
  const identityKey = validateIdentityKey(payload.identityKey, errors)
    ? payload.identityKey
    : undefined;
  if (seatId !== undefined && identityKey !== undefined) {
    try {
      if ((await computeSeatId(identityKey, SEAT_ID_ALGORITHM_VERSION)) !== seatId) {
        errors.push("seatId does not match identityKey and seatIdAlgorithm");
      }
    } catch (error) {
      errors.push(error instanceof Error ? error.message : "seat id computation failed");
    }
  }
  const seatKind = requiredString(payload, "seatKind", errors);
  if (seatKind !== undefined && !SEAT_KINDS.has(seatKind)) {
    errors.push("seatKind must be BROKER_BRANCH, INSTITUTION, UNKNOWN or OTHER");
  }
  if (payload.canonicalName !== null && typeof payload.canonicalName !== "string") {
    errors.push("canonicalName must be a string or null");
  }
  const validity = interval(payload, "validFrom", "validTo", errors);
  instant(payload.availableTime, "availableTime", errors);
  validateRevisionChain(payload, errors);
  validateLineage(payload, seatId, validity.from, validity.to, errors);
  return result(errors);
}

function validateBaseRecord(
  input: unknown,
  schemaVersion: string,
): { payload: JsonRecord | null; errors: string[] } {
  const payload = record(input);
  if (payload === null) return { payload: null, errors: ["payload must be an object"] };
  const errors: string[] = [];
  if (payload.schemaVersion !== schemaVersion)
    errors.push(`schemaVersion must be ${schemaVersion}`);
  validateSeatId(payload.seatId, "seatId", errors);
  validateRevisionChain(payload, errors);
  return { payload, errors };
}

export function validateAliasPayload(input: unknown): ValidationResult {
  const { payload, errors } = validateBaseRecord(input, "alias-v1");
  if (payload === null) return result(errors);
  requiredString(payload, "aliasId", errors);
  requiredString(payload, "name", errors);
  const aliasType = requiredString(payload, "aliasType", errors);
  if (aliasType !== undefined && !ALIAS_TYPES.has(aliasType)) {
    errors.push("aliasType must be OFFICIAL, FORMER, SOURCE or ALTERNATE");
  }
  interval(payload, "validFrom", "validTo", errors);
  instant(payload.availableTime, "availableTime", errors);
  requiredString(payload, "source", errors);
  requiredString(payload, "sourceVersion", errors);
  requiredString(payload, "evidenceId", errors);
  return result(errors);
}

export function validatePerformancePayload(input: unknown): ValidationResult {
  const { payload, errors } = validateBaseRecord(input, "seat-performance-v1");
  if (payload === null) return result(errors);
  requiredString(payload, "performanceId", errors);
  dateOnly(payload.windowStart, "windowStart", errors);
  dateOnly(payload.windowEnd, "windowEnd", errors);
  if (
    typeof payload.windowStart === "string" &&
    typeof payload.windowEnd === "string" &&
    payload.windowEnd < payload.windowStart
  ) {
    errors.push("windowEnd must be greater than or equal to windowStart");
  }
  requiredString(payload, "calculationVersion", errors);
  if (
    typeof payload.sampleCount !== "number" ||
    !Number.isInteger(payload.sampleCount) ||
    payload.sampleCount < 0
  ) {
    errors.push("sampleCount must be a non-negative integer");
  }
  for (const field of ["tPlus1Return", "tPlus3Return", "tPlus5Return", "winRate", "maxDrawdown"]) {
    if (payload[field] !== null && parseDecimal(payload[field]) === null) {
      errors.push(`${field} must be a decimal string or null`);
    }
  }
  instant(payload.availableTime, "availableTime", errors);
  requiredString(payload, "source", errors);
  requiredString(payload, "sourceVersion", errors);
  requiredString(payload, "evidenceId", errors);
  return result(errors);
}

export function validatePreferencePayload(input: unknown): ValidationResult {
  const { payload, errors } = validateBaseRecord(input, "seat-preference-v1");
  if (payload === null) return result(errors);
  requiredString(payload, "preferenceId", errors);
  interval(payload, "validFrom", "validTo", errors);
  requiredString(payload, "preferenceVersion", errors);
  const tags = payload.styleTags;
  if (!Array.isArray(tags) || tags.some((tag) => typeof tag !== "string" || tag.length === 0)) {
    errors.push("styleTags must be a non-empty string array");
  } else if (tags.length === 0 || new Set(tags).size !== tags.length) {
    errors.push("styleTags must be non-empty and unique");
  }
  if (
    typeof payload.confidenceBps !== "number" ||
    !Number.isInteger(payload.confidenceBps) ||
    payload.confidenceBps < 0 ||
    payload.confidenceBps > 10000
  ) {
    errors.push("confidenceBps must be an integer in [0, 10000]");
  }
  instant(payload.availableTime, "availableTime", errors);
  requiredString(payload, "source", errors);
  requiredString(payload, "sourceVersion", errors);
  requiredString(payload, "evidenceId", errors);
  return result(errors);
}

function parseDecimal(value: unknown): ParsedDecimal | null {
  if (typeof value !== "string" || !DECIMAL_PATTERN.test(value)) return null;
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const point = unsigned.indexOf(".");
  const whole = point === -1 ? unsigned : unsigned.slice(0, point);
  const fraction = point === -1 ? "" : unsigned.slice(point + 1);
  const digits = `${whole}${fraction}`.replace(/^0+(?=\d)/, "");
  return { negative, unscaled: BigInt(`${negative ? "-" : ""}${digits}`), scale: fraction.length };
}

function scaled(value: ParsedDecimal, scale: number): bigint {
  return value.unscaled * 10n ** BigInt(scale - value.scale);
}

function subtractionMatches(buy: ParsedDecimal, sell: ParsedDecimal, net: ParsedDecimal): boolean {
  const scale =
    buy.scale > sell.scale
      ? buy.scale > net.scale
        ? buy.scale
        : net.scale
      : sell.scale > net.scale
        ? sell.scale
        : net.scale;
  return scaled(net, scale) === scaled(buy, scale) - scaled(sell, scale);
}

export function validateTradePayload(input: unknown): ValidationResult {
  const { payload, errors } = validateBaseRecord(input, "seat-trade-v1");
  if (payload === null) return result(errors);
  requiredString(payload, "tradeId", errors);
  requiredString(payload, "rawSeatName", errors);
  if (
    typeof payload.instrumentId !== "string" ||
    !INSTRUMENT_ID_PATTERN.test(payload.instrumentId)
  ) {
    errors.push("instrumentId must use canonical unified code form");
  }
  dateOnly(payload.tradeDate, "tradeDate", errors);
  if (payload.currency !== "CNY") errors.push("currency must be CNY");
  const buy = parseDecimal(payload.buyAmount);
  const sell = parseDecimal(payload.sellAmount);
  const net = parseDecimal(payload.netAmount);
  if (buy === null) errors.push("buyAmount must be a decimal string");
  if (sell === null) errors.push("sellAmount must be a decimal string");
  if (net === null) errors.push("netAmount must be a decimal string");
  if (buy !== null && buy.negative) errors.push("buyAmount must be non-negative");
  if (sell !== null && sell.negative) errors.push("sellAmount must be non-negative");
  if (buy !== null && sell !== null && net !== null && !subtractionMatches(buy, sell, net)) {
    errors.push("netAmount must equal buyAmount - sellAmount");
  }
  requiredString(payload, "source", errors);
  requiredString(payload, "sourceVersion", errors);
  requiredString(payload, "rawRecordId", errors);
  requiredString(payload, "evidenceId", errors);
  instant(payload.availableTime, "availableTime", errors);
  return result(errors);
}
