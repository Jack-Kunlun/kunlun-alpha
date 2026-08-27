import { isRfc3339Instant } from "../../common/rfc3339";

const ALLOWED_KEYS = new Set(["mode", "asOf"]);

export class PreciousMetalsValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PreciousMetalsValidationError";
  }
}

export interface PreciousMetalsClock {
  now(): Date;
}

export class SystemPreciousMetalsClock implements PreciousMetalsClock {
  now(): Date {
    return new Date();
  }
}

export interface PreciousMetalsQuery {
  mode: "CURRENT" | "HISTORICAL";
  requestedAsOf: string;
  effectiveAsOf: string;
  generatedAt: string;
}

export function parsePreciousMetalsQuery(
  value: Record<string, unknown>,
  clock: PreciousMetalsClock,
): PreciousMetalsQuery {
  for (const key of Object.keys(value)) {
    if (!ALLOWED_KEYS.has(key)) {
      throw new PreciousMetalsValidationError("unsupported query parameter: " + key);
    }
  }
  const now = clock.now();
  const generatedAt = now.toISOString();
  const inferredMode = value["asOf"] === undefined ? "CURRENT" : "HISTORICAL";
  const mode = value["mode"] ?? inferredMode;
  if (mode !== "CURRENT" && mode !== "HISTORICAL") {
    throw new PreciousMetalsValidationError("mode must be CURRENT or HISTORICAL");
  }
  if (mode === "CURRENT" && value["asOf"] !== undefined) {
    throw new PreciousMetalsValidationError("CURRENT mode must not provide asOf");
  }
  if (mode === "HISTORICAL" && value["asOf"] === undefined) {
    throw new PreciousMetalsValidationError("HISTORICAL mode requires asOf");
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
    throw new PreciousMetalsValidationError("asOf must be a timezone-aware RFC3339 instant");
  }
  const effectiveAsOf = new Date(rawAsOf).toISOString();
  if (Date.parse(effectiveAsOf) > now.getTime()) {
    throw new PreciousMetalsValidationError("asOf must not be in the future");
  }
  return {
    mode,
    requestedAsOf: effectiveAsOf,
    effectiveAsOf,
    generatedAt,
  };
}
