import { isRfc3339Instant } from "../../common/rfc3339";

const INSTRUMENT = /^[0-9]{6}\.(SH|SZ|BJ)$/;
const ALLOWED_KEYS = new Set(["mode", "asOf"]);

export class InstrumentIntelligenceValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InstrumentIntelligenceValidationError";
  }
}

export interface InstrumentIntelligenceQuery {
  mode: "CURRENT" | "HISTORICAL";
  requestedAsOf: string;
  effectiveAsOf: string;
  generatedAt: string;
}

export interface InstrumentIntelligenceClock {
  now(): Date;
}

export class SystemInstrumentIntelligenceClock implements InstrumentIntelligenceClock {
  now(): Date {
    return new Date();
  }
}

export function parseInstrumentId(value: string): string {
  if (!INSTRUMENT.test(value)) {
    throw new InstrumentIntelligenceValidationError(
      "instrumentId must use the canonical 600519.SH form",
    );
  }
  return value;
}

export function parseInstrumentIntelligenceQuery(
  value: Record<string, unknown>,
  clock: InstrumentIntelligenceClock,
): InstrumentIntelligenceQuery {
  for (const key of Object.keys(value)) {
    if (!ALLOWED_KEYS.has(key)) {
      throw new InstrumentIntelligenceValidationError("unsupported query parameter: " + key);
    }
  }
  const now = clock.now();
  const generatedAt = now.toISOString();
  const inferredMode = value["asOf"] === undefined ? "CURRENT" : "HISTORICAL";
  const mode = value["mode"] ?? inferredMode;
  if (mode !== "CURRENT" && mode !== "HISTORICAL") {
    throw new InstrumentIntelligenceValidationError("mode must be CURRENT or HISTORICAL");
  }
  if (mode === "CURRENT" && value["asOf"] !== undefined) {
    throw new InstrumentIntelligenceValidationError("CURRENT mode must not provide asOf");
  }
  if (mode === "HISTORICAL" && value["asOf"] === undefined) {
    throw new InstrumentIntelligenceValidationError("HISTORICAL mode requires asOf");
  }
  if (mode === "CURRENT") {
    return {
      mode,
      requestedAsOf: generatedAt,
      effectiveAsOf: generatedAt,
      generatedAt,
    };
  }
  const rawAsOf = value["asOf"];
  if (typeof rawAsOf !== "string" || !isRfc3339Instant(rawAsOf)) {
    throw new InstrumentIntelligenceValidationError(
      "asOf must be a timezone-aware RFC3339 instant",
    );
  }
  const effectiveAsOf = new Date(rawAsOf).toISOString();
  if (Date.parse(effectiveAsOf) > now.getTime()) {
    throw new InstrumentIntelligenceValidationError("asOf must not be in the future");
  }
  return {
    mode,
    requestedAsOf: effectiveAsOf,
    effectiveAsOf,
    generatedAt,
  };
}
