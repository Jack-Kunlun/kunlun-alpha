/**
 * Code parser tests driven by packages/contracts/instrument/fixtures.json.
 * The same fixture file drives the Python pytest suite in market-core, so the
 * two parsers stay aligned.
 */

import { describe, expect, it } from "vitest";
import { parseInstrument, parseInstrumentCode, toUnifiedCode, validateInstrument } from "./code-parser";
import fixtures from "../../instrument/fixtures.json";

interface ValidFixture {
  code: string;
  exchange: "SH" | "SZ" | "BJ";
  board: "MAIN" | "CHINEXT" | "STAR" | "BSE";
  type: "STOCK" | "ETF" | "LOF" | "FUND";
  unifiedCode: string;
  note: string;
}

interface InvalidFixture {
  code: string;
  reason: string;
}

interface StatusFixture {
  code: string;
  tradingStatus: "LISTED" | "SUSPENDED" | "ST" | "DELISTED";
  note: string;
}

describe("parseInstrumentCode — valid codes", () => {
  const valid = fixtures.valid as ValidFixture[];
  it.each(valid.map((f) => [f.code, f] as const))("parses %s", (_code, fixture) => {
    const ref = parseInstrumentCode(fixture.code);
    expect(ref).not.toBeNull();
    expect(ref?.exchange).toBe(fixture.exchange);
    expect(ref?.board).toBe(fixture.board);
    expect(ref?.type).toBe(fixture.type);
    expect(ref?.unifiedCode).toBe(fixture.unifiedCode);
  });
});

describe("parseInstrumentCode — invalid codes", () => {
  const invalid = fixtures.invalid as InvalidFixture[];
  it.each(invalid.map((f) => [f.code, f.reason] as const))("rejects %j (%s)", (code, reason) => {
    expect(parseInstrumentCode(code)).toBeNull();
    void reason;
  });

  it("rejects the obsolete exchange-prefix form", () => {
    expect(parseInstrumentCode("SH.600519")).toBeNull();
  });
});

describe("parseInstrumentCode — ST / delisted / suspended keep their code", () => {
  const statuses = fixtures.stAndDelisted as StatusFixture[];
  it.each(statuses.map((f) => [f.code, f.tradingStatus] as const))(
    "still parses %s even when %s",
    (code, tradingStatus) => {
      const ref = parseInstrumentCode(code);
      expect(ref).not.toBeNull();
      expect(ref?.unifiedCode).toContain(`${code}`);
      void tradingStatus;
    },
  );
});

describe("toUnifiedCode", () => {
  it("builds a unified code from exchange + code", () => {
    expect(toUnifiedCode("SH", "600519")).toBe("600519.SH");
  });

  it("trims whitespace", () => {
    expect(toUnifiedCode("SZ", " 000001 ")).toBe("000001.SZ");
  });

  it("rejects an exchange that does not match the code prefix", () => {
    expect(toUnifiedCode("SZ", "600519")).toBeNull();
  });

  it("returns null for malformed codes", () => {
    expect(toUnifiedCode("SH", "abc")).toBeNull();
    expect(toUnifiedCode("SH", "12345")).toBeNull();
  });
});

const validInstrument = {
  unifiedCode: "600519.SH",
  code: "600519",
  exchange: "SH",
  board: "MAIN",
  type: "STOCK",
  name: "贵州茅台",
  tradingStatus: "LISTED",
  currency: "CNY",
} as const;

describe("Instrument deserialization boundary", () => {
  it("accepts a complete instrument whose code, exchange and unified code agree", () => {
    expect(validateInstrument(validInstrument)).toEqual({ valid: true, errors: [] });
    expect(parseInstrument(validInstrument)).toEqual(validInstrument);
  });

  it.each([
    ["code mismatch", { ...validInstrument, code: "000001" }],
    ["exchange mismatch", { ...validInstrument, exchange: "SZ" }],
    ["suffix mismatch", { ...validInstrument, unifiedCode: "SH.600519" }],
    [
      "prefix-rule exchange mismatch",
      { ...validInstrument, unifiedCode: "600519.SZ", exchange: "SZ" },
    ],
  ] as const)("rejects %s", (_reason, input) => {
    const result = validateInstrument(input);
    expect(result.valid).toBe(false);
    expect(result.errors.length).toBeGreaterThan(0);
    expect(parseInstrument(input)).toBeNull();
  });
});
