import type {
  Instrument,
  KolClaim,
  KolEvidence,
  SeatTrade,
  Sector,
  SectorMembership,
} from "@kunlun/shared-types";
import { isRfc3339Instant } from "../../common/rfc3339";

const INSTRUMENT = /^[0-9]{6}\.(SH|SZ|BJ)$/;
const DECIMAL = /^-?(0|[1-9][0-9]*)(\.[0-9]+)?$/;

function record(value: unknown, name: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("invalid persisted " + name + " payload");
  }
  return value as Record<string, unknown>;
}

function text(input: Record<string, unknown>, field: string): string {
  const value = input[field];
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error("invalid persisted field: " + field);
  }
  return value;
}

function instant(input: Record<string, unknown>, field: string): string {
  const value = text(input, field);
  if (!isRfc3339Instant(value)) throw new Error("invalid persisted instant: " + field);
  return value;
}

function optionalDate(input: Record<string, unknown>, field: string): boolean {
  const value = input[field];
  return value === undefined || (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value));
}

function date(input: Record<string, unknown>, field: string): boolean {
  const value = input[field];
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
}

function nullableDate(input: Record<string, unknown>, field: string): boolean {
  const value = input[field];
  return value === undefined || value === null || date(input, field);
}

export function validateInstrumentPayload(value: unknown): Instrument {
  const input = record(value, "Instrument");
  const unifiedCode = text(input, "unifiedCode");
  const code = text(input, "code");
  const exchange = text(input, "exchange");
  if (
    !INSTRUMENT.test(unifiedCode) ||
    !/^[0-9]{6}$/.test(code) ||
    unifiedCode !== code + "." + exchange ||
    !["SH", "SZ", "BJ"].includes(exchange) ||
    !["MAIN", "CHINEXT", "STAR", "BSE"].includes(text(input, "board")) ||
    !["STOCK", "ETF", "LOF", "FUND"].includes(text(input, "type")) ||
    !["LISTED", "SUSPENDED", "ST", "DELISTED"].includes(text(input, "tradingStatus")) ||
    input["currency"] !== "CNY" ||
    !optionalDate(input, "listDate") ||
    !optionalDate(input, "delistDate")
  ) {
    throw new Error("invalid persisted Instrument payload");
  }
  text(input, "name");
  return value as Instrument;
}

export function validateSectorPayload(value: unknown): Sector {
  const input = record(value, "Sector");
  if (
    !["INDUSTRY", "CONCEPT", "THEME"].includes(text(input, "kind")) ||
    !Array.isArray(input["aliases"]) ||
    input["aliases"].some((item) => typeof item !== "string") ||
    !date(input, "validFrom") ||
    !nullableDate(input, "validTo")
  ) {
    throw new Error("invalid persisted Sector payload");
  }
  for (const field of ["sectorId", "name", "source", "sourceVersion", "evidenceId"])
    text(input, field);
  instant(input, "availableTime");
  return value as Sector;
}

export function validateSectorMembershipPayload(value: unknown): SectorMembership {
  const input = record(value, "SectorMembership");
  if (
    !INSTRUMENT.test(text(input, "unifiedCode")) ||
    !date(input, "validFrom") ||
    !nullableDate(input, "validTo")
  ) {
    throw new Error("invalid persisted SectorMembership payload");
  }
  for (const field of ["sectorId", "source", "sourceVersion", "evidenceId"]) text(input, field);
  instant(input, "availableTime");
  return value as SectorMembership;
}

export function validateSeatTradePayload(value: unknown): SeatTrade {
  const input = record(value, "SeatTrade");
  if (
    input["schemaVersion"] !== "seat-trade-v1" ||
    !INSTRUMENT.test(text(input, "instrumentId")) ||
    input["currency"] !== "CNY" ||
    !DECIMAL.test(text(input, "buyAmount")) ||
    !DECIMAL.test(text(input, "sellAmount")) ||
    !DECIMAL.test(text(input, "netAmount")) ||
    !/^\d{4}-\d{2}-\d{2}$/.test(text(input, "tradeDate"))
  ) {
    throw new Error("invalid persisted SeatTrade payload");
  }
  for (const field of [
    "tradeId",
    "revisionId",
    "seatId",
    "rawSeatName",
    "source",
    "sourceVersion",
    "rawRecordId",
    "evidenceId",
  ]) {
    text(input, field);
  }
  instant(input, "availableTime");
  return value as SeatTrade;
}

export function validateKolClaimPayload(value: unknown): KolClaim {
  const input = record(value, "KolClaim");
  const evidence = input["evidence"];
  if (
    input["schemaVersion"] !== "kol-claim-v1" ||
    !INSTRUMENT.test(text(input, "instrumentId")) ||
    !Number.isInteger(input["confidenceBps"]) ||
    Number(input["confidenceBps"]) < 0 ||
    Number(input["confidenceBps"]) > 10_000 ||
    !["UNREVIEWED", "IN_REVIEW", "APPROVED", "REJECTED"].includes(text(input, "reviewStatus")) ||
    typeof input["deleted"] !== "boolean" ||
    !Array.isArray(evidence) ||
    evidence.length === 0 ||
    evidence.some((item) => {
      const candidate = record(item, "KolClaim evidence");
      return typeof candidate["evidenceId"] !== "string" || candidate["evidenceId"] === "";
    })
  ) {
    throw new Error("invalid persisted KolClaim payload");
  }
  for (const field of [
    "claimId",
    "revisionId",
    "contentId",
    "contentVersion",
    "kolId",
    "statement",
    "direction",
    "source",
    "sourceVersion",
  ]) {
    text(input, field);
  }
  const publishTime = instant(input, "publishTime");
  const ingestTime = instant(input, "ingestTime");
  const processingTime = instant(input, "processingTime");
  const availableTime = instant(input, "availableTime");
  if (
    Date.parse(publishTime) > Date.parse(ingestTime) ||
    Date.parse(ingestTime) > Date.parse(processingTime) ||
    Date.parse(processingTime) > Date.parse(availableTime)
  ) {
    throw new Error("invalid persisted KolClaim time order");
  }
  return value as KolClaim;
}

export function validateKolEvidencePayload(value: unknown): KolEvidence {
  const input = record(value, "KolEvidence");
  if (
    input["schemaVersion"] !== "kol-evidence-v1" ||
    !["URL", "TEXT_RANGE", "TIME_RANGE", "PAGE"].includes(text(input, "locatorType")) ||
    !["PRIMARY_SOURCE", "SECONDARY_SOURCE", "TERTIARY_SOURCE", "UNCLASSIFIED"].includes(
      text(input, "evidenceGrade"),
    )
  ) {
    throw new Error("invalid persisted KolEvidence payload");
  }
  for (const field of [
    "evidenceId",
    "revisionId",
    "contentId",
    "contentVersion",
    "source",
    "sourceVersion",
    "locator",
    "excerpt",
  ]) {
    text(input, field);
  }
  instant(input, "contentAvailableTime");
  instant(input, "availableTime");
  return value as KolEvidence;
}
