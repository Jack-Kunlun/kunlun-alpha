import type {
  PaperTerminalCreateAccountCommand,
  PaperTerminalSimulationCommand,
} from "@kunlun/shared-types";

export class PaperTerminalValidationError extends Error {}

const REQUEST_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$/;
const INSTRUMENT_ID = /^[0-9]{6}\.(?:SH|SZ|BJ)$/;
const POSITIVE_DECIMAL = /^(?:0\.\d*[1-9]\d*|[1-9]\d*(?:\.\d+)?)$/;
const RATIO = /^(?:0(?:\.\d+)?|1(?:\.0+)?)$/;

export function parseCreateAccount(body: unknown): PaperTerminalCreateAccountCommand {
  const value = exactRecord(body, ["schemaVersion", "clientRequestId", "name", "initialCapital"]);
  if (value["schemaVersion"] !== "paper-terminal-create-account-v1") fail("schemaVersion");
  const clientRequestId = boundedString(value["clientRequestId"], "clientRequestId", 128);
  if (!REQUEST_ID.test(clientRequestId)) fail("clientRequestId");
  const name = boundedString(value["name"], "name", 80);
  const initialCapital = boundedString(value["initialCapital"], "initialCapital", 32);
  if (!POSITIVE_DECIMAL.test(initialCapital)) fail("initialCapital");
  return {
    schemaVersion: "paper-terminal-create-account-v1",
    clientRequestId,
    name,
    initialCapital,
  };
}

export function parseSimulation(body: unknown): PaperTerminalSimulationCommand {
  const value = exactRecord(body, [
    "schemaVersion",
    "clientRequestId",
    "instrumentId",
    "price",
    "score",
    "confidence",
    "lotSize",
  ]);
  if (value["schemaVersion"] !== "paper-terminal-simulation-v1") fail("schemaVersion");
  const clientRequestId = boundedString(value["clientRequestId"], "clientRequestId", 128);
  const instrumentId = boundedString(value["instrumentId"], "instrumentId", 9);
  const price = boundedString(value["price"], "price", 32);
  const score = boundedString(value["score"], "score", 20);
  const confidence = boundedString(value["confidence"], "confidence", 20);
  const lotSize = value["lotSize"];
  if (!REQUEST_ID.test(clientRequestId)) fail("clientRequestId");
  if (!INSTRUMENT_ID.test(instrumentId)) fail("instrumentId");
  if (!POSITIVE_DECIMAL.test(price)) fail("price");
  if (!RATIO.test(score)) fail("score");
  if (!RATIO.test(confidence)) fail("confidence");
  if (!Number.isInteger(lotSize) || (lotSize as number) < 1 || (lotSize as number) > 10_000) {
    fail("lotSize");
  }
  return {
    schemaVersion: "paper-terminal-simulation-v1",
    clientRequestId,
    instrumentId,
    price,
    score,
    confidence,
    lotSize: lotSize as number,
  };
}

function exactRecord(value: unknown, keys: readonly string[]): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail("body");
  const record = value as Record<string, unknown>;
  const expected = new Set(keys);
  if (Object.keys(record).some((key) => !expected.has(key))) fail("unexpected field");
  if (keys.some((key) => !(key in record))) fail("missing field");
  return record;
}

function boundedString(value: unknown, field: string, maxLength: number): string {
  if (typeof value !== "string" || value.length === 0 || value.length > maxLength) fail(field);
  return value as string;
}

function fail(field: string): never {
  throw new PaperTerminalValidationError(`invalid paper terminal field: ${field}`);
}
