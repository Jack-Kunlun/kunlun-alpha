/**
 * A-share instrument code parser.
 *
 * Normalizes any external 6-digit code into the unified form used by the
 * domain layer: {code}.{EXCHANGE} (e.g. 600000.SH). The prefix rules come
 * from packages/contracts/instrument/code-prefix-rules.json — the single
 * source of truth shared with the Python parser in market-core.
 */

import codePrefixRules from "../../instrument/code-prefix-rules.json";

export type ExchangeCode = "SH" | "SZ" | "BJ";
export type BoardId = "MAIN" | "CHINEXT" | "STAR" | "BSE";
export type SecurityType = "STOCK" | "ETF" | "LOF" | "FUND";
export type TradingStatus = "LISTED" | "SUSPENDED" | "ST" | "DELISTED";

/** Runtime shape accepted at the complete Instrument domain boundary. */
export interface InstrumentRecord {
  unifiedCode: string;
  code: string;
  exchange: ExchangeCode;
  board: BoardId;
  type: SecurityType;
  name: string;
  tradingStatus: TradingStatus;
  currency: "CNY";
  listDate?: string;
  delistDate?: string;
}

export interface InstrumentValidationResult {
  valid: boolean;
  errors: string[];
}

export interface InstrumentCodeRef {
  /** Raw 6-digit exchange code. */
  code: string;
  /** Unified domain key, e.g. "600000.SH". */
  unifiedCode: string;
  exchange: ExchangeCode;
  board: BoardId;
  type: SecurityType;
}

interface PrefixRule {
  prefix: string;
  exchange: ExchangeCode;
  board: BoardId;
  type: SecurityType;
}

/** Rules sorted by prefix length descending so longer prefixes win. */
const rules: PrefixRule[] = [...(codePrefixRules as { rules: PrefixRule[] }).rules].sort(
  (a, b) => b.prefix.length - a.prefix.length,
);

const CODE_RE = /^\d{6}$/;

/**
 * Parse a raw 6-digit A-share code into the unified instrument reference.
 * Returns null when the input is not a valid exchange code (bad format or
 * unassigned code segment).
 */
export function parseInstrumentCode(input: string): InstrumentCodeRef | null {
  const code = input.trim();
  if (!CODE_RE.test(code)) {
    return null;
  }
  for (const rule of rules) {
    if (code.startsWith(rule.prefix)) {
      return {
        code,
        unifiedCode: `${code}.${rule.exchange}`,
        exchange: rule.exchange,
        board: rule.board,
        type: rule.type,
      };
    }
  }
  return null;
}

/** Build a unified code from a known exchange and a raw 6-digit code. */
export function toUnifiedCode(exchange: ExchangeCode, code: string): string | null {
  const normalizedCode = code.trim();
  if (!CODE_RE.test(normalizedCode)) {
    return null;
  }
  const parsed = parseInstrumentCode(normalizedCode);
  if (parsed === null || parsed.exchange !== exchange) {
    return null;
  }
  return parsed.unifiedCode;
}

/**
 * Check suffix/exchange identity and shared prefix ownership for market data.
 */
export function isUnifiedCodeForExchange(unifiedCode: string, exchange: ExchangeCode): boolean {
  const match = /^(\d{6})\.(SH|SZ|BJ)$/.exec(unifiedCode);
  if (match === null) return false;
  const code = match[1];
  const suffix = match[2];
  if (code === undefined || suffix === undefined || suffix !== exchange) return false;
  const parsed = parseInstrumentCode(code);
  return parsed !== null && parsed.exchange === exchange;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasString(value: Record<string, unknown>, key: string): value is Record<string, string> {
  return typeof value[key] === "string";
}

/**
 * Validate a complete Instrument before it enters the domain layer.
 *
 * The generated `Instrument` type is compile-time only, so this boundary
 * performs the cross-field identity check that JSON Schema cannot express in
 * the generated TypeScript runtime. Raw code parsing remains the single
 * source of truth for code/exchange agreement.
 */
export function validateInstrument(input: unknown): InstrumentValidationResult {
  if (!isRecord(input)) {
    return { valid: false, errors: ["instrument must be an object"] };
  }

  const errors: string[] = [];
  const allowedFields = new Set([
    "unifiedCode",
    "code",
    "exchange",
    "board",
    "type",
    "name",
    "tradingStatus",
    "currency",
    "listDate",
    "delistDate",
  ]);
  for (const field of Object.keys(input)) {
    if (!allowedFields.has(field)) {
      errors.push(`${field} is not permitted`);
    }
  }
  const requiredStringFields = [
    "unifiedCode",
    "code",
    "exchange",
    "board",
    "type",
    "name",
    "tradingStatus",
    "currency",
  ] as const;

  for (const field of requiredStringFields) {
    if (!hasString(input, field)) {
      errors.push(`${field} must be a string`);
    }
  }
  if (errors.length > 0) {
    return { valid: false, errors };
  }
  const stringInput = input as {
    unifiedCode: string;
    code: string;
    exchange: string;
    board: string;
    type: string;
    tradingStatus: string;
    currency: string;
  };

  if (!["SH", "SZ", "BJ"].includes(stringInput.exchange)) {
    errors.push("exchange must be SH/SZ/BJ");
  }
  if (!["MAIN", "CHINEXT", "STAR", "BSE"].includes(stringInput.board)) {
    errors.push("board is invalid");
  }
  if (!["STOCK", "ETF", "LOF", "FUND"].includes(stringInput.type)) {
    errors.push("type is invalid");
  }
  if (!["LISTED", "SUSPENDED", "ST", "DELISTED"].includes(stringInput.tradingStatus)) {
    errors.push("tradingStatus is invalid");
  }
  if (stringInput.currency !== "CNY") {
    errors.push("currency must be CNY");
  }

  const parsed = parseInstrumentCode(stringInput.code);
  if (parsed === null) {
    errors.push("code must be a recognized 6-digit instrument code");
  } else {
    if (parsed.exchange !== stringInput.exchange) {
      errors.push("exchange must match code");
    }
    if (parsed.board !== stringInput.board) {
      errors.push("board must match code");
    }
    if (parsed.type !== stringInput.type) {
      errors.push("type must match code");
    }
    if (parsed.unifiedCode !== stringInput.unifiedCode) {
      errors.push("unifiedCode must match code and exchange");
    }
  }

  for (const field of ["listDate", "delistDate"] as const) {
    if (input[field] === undefined) {
      continue;
    }
    if (typeof input[field] !== "string") {
      errors.push(`${field} must be a string when provided`);
      continue;
    }
    if (!isIsoDate(input[field])) {
      errors.push(`${field} must be a valid ISO date`);
    }
  }

  return { valid: errors.length === 0, errors };
}

function isIsoDate(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (match === null) {
    return false;
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

/** Parse a complete Instrument, returning null instead of crossing the boundary with invalid data. */
export function parseInstrument(input: unknown): InstrumentRecord | null {
  if (!validateInstrument(input).valid) {
    return null;
  }
  return input as InstrumentRecord;
}
