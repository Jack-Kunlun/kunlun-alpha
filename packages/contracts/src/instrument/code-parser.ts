/**
 * A-share instrument code parser.
 *
 * Normalizes any external 6-digit code into the unified form used by the
 * domain layer: {EXCHANGE}.{code} (e.g. SH.600000). The prefix rules come
 * from packages/contracts/instrument/code-prefix-rules.json — the single
 * source of truth shared with the Python parser in market-core.
 */

import codePrefixRules from "../../instrument/code-prefix-rules.json";

export type ExchangeCode = "SH" | "SZ" | "BJ";
export type BoardId = "MAIN" | "CHINEXT" | "STAR" | "BSE";
export type SecurityType = "STOCK" | "ETF" | "LOF" | "FUND";

export interface InstrumentCodeRef {
  /** Raw 6-digit exchange code. */
  code: string;
  /** Unified domain key, e.g. "SH.600000". */
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
        unifiedCode: `${rule.exchange}.${code}`,
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
  if (!CODE_RE.test(code.trim())) {
    return null;
  }
  return `${exchange}.${code.trim()}`;
}
