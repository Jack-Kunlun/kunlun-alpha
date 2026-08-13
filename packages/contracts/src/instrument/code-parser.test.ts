/**
 * Code parser tests driven by packages/contracts/instrument/fixtures.json.
 * The same fixture file drives the Python pytest suite in market-core, so the
 * two parsers stay aligned.
 */

import { describe, expect, it } from "vitest";
import { parseInstrumentCode, toUnifiedCode } from "./code-parser";
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
  it.each(invalid.map((f) => [f.code, f.reason] as const))(
    "rejects %j (%s)",
    (code, reason) => {
      expect(parseInstrumentCode(code)).toBeNull();
      void reason;
    },
  );
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
    expect(toUnifiedCode("SH", "600000")).toBe("SH.600000");
  });

  it("trims whitespace", () => {
    expect(toUnifiedCode("SZ", " 000001 ")).toBe("SZ.000001");
  });

  it("returns null for malformed codes", () => {
    expect(toUnifiedCode("SH", "abc")).toBeNull();
    expect(toUnifiedCode("SH", "12345")).toBeNull();
  });
});
