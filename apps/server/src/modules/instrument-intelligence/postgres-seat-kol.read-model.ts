import type { KolClaim, KolEvidence, SeatTrade } from "@kunlun/shared-types";
import type { PoolClient, QueryResultRow } from "pg";
import { pgBoolean, pgInstant, pgText, sourceVersion } from "./pg-row";
import {
  validateKolClaimPayload,
  validateKolEvidencePayload,
  validateSeatTradePayload,
} from "./pit-validation";
import type { PitRecord } from "./read-model.types";

interface SeatRow extends QueryResultRow {
  payload: unknown;
  event_time: unknown;
  available_time: unknown;
  processing_time: unknown;
  evidence_id: unknown;
}

interface ClaimRow extends QueryResultRow {
  payload: unknown;
  event_time: unknown;
  available_time: unknown;
  processing_time: unknown;
  deleted: unknown;
}

interface EvidenceRow extends QueryResultRow {
  payload: unknown;
  available_time: unknown;
  processing_time: unknown;
  source: unknown;
  source_version: unknown;
}

const SEAT_SQL = [
  "SELECT payload, event_time, available_time, processing_time, evidence_id",
  "FROM (",
  "  SELECT DISTINCT ON (trade_id)",
  "    trade_id, payload, event_time, available_time, processing_time, evidence_id, revision_id",
  "  FROM seat_trade_intelligence_revisions",
  "  WHERE instrument_id = $1",
  "    AND event_time <= $2::timestamptz",
  "    AND available_time <= $2::timestamptz",
  "    AND processing_time <= $2::timestamptz",
  "  ORDER BY trade_id, available_time DESC, processing_time DESC, revision_id DESC",
  ") latest",
  "ORDER BY event_time DESC, trade_id",
  "LIMIT 100",
].join("\n");

const CLAIM_SQL = [
  "SELECT payload, event_time, available_time, processing_time, deleted",
  "FROM (",
  "  SELECT DISTINCT ON (claim_id)",
  "    claim_id, payload, event_time, available_time, processing_time, deleted, revision_id",
  "  FROM kol_claim_intelligence_revisions",
  "  WHERE instrument_id = $1",
  "    AND available_time <= $2::timestamptz",
  "    AND processing_time <= $2::timestamptz",
  "  ORDER BY claim_id, available_time DESC, processing_time DESC, revision_id DESC",
  ") latest",
  "WHERE deleted = FALSE",
  "ORDER BY available_time DESC, claim_id",
  "LIMIT 100",
].join("\n");

const EVIDENCE_SQL = [
  "SELECT payload, available_time, processing_time, source, source_version",
  "FROM (",
  "  SELECT DISTINCT ON (evidence_id)",
  "    evidence_id, payload, available_time, processing_time, source, source_version, revision_id",
  "  FROM intelligence_evidence_revisions",
  "  WHERE evidence_id = ANY($1::text[])",
  "    AND available_time <= $2::timestamptz",
  "    AND processing_time <= $2::timestamptz",
  "  ORDER BY evidence_id, available_time DESC, processing_time DESC, revision_id DESC",
  ") latest",
  "ORDER BY evidence_id",
].join("\n");

export async function loadSeatTrades(
  client: Pick<PoolClient, "query">,
  instrumentId: string,
  asOf: string,
): Promise<PitRecord<SeatTrade>[]> {
  const result = await client.query<SeatRow>(SEAT_SQL, [instrumentId, asOf]);
  return result.rows.map((row) => {
    const data = validateSeatTradePayload(row.payload);
    return {
      data,
      eventTime: pgInstant(row.event_time, "event_time"),
      availableTime: pgInstant(row.available_time, "available_time"),
      processingTime: pgInstant(row.processing_time, "processing_time"),
      sourceVersions: [sourceVersion(data.source, data.sourceVersion)],
      evidenceIds: [pgText(row.evidence_id, "evidence_id")],
    };
  });
}

export async function loadKolClaims(
  client: Pick<PoolClient, "query">,
  instrumentId: string,
  asOf: string,
): Promise<PitRecord<KolClaim>[]> {
  const result = await client.query<ClaimRow>(CLAIM_SQL, [instrumentId, asOf]);
  return result.rows.map((row) => {
    const data = validateKolClaimPayload(row.payload);
    if (pgBoolean(row.deleted, "deleted") !== data.deleted) {
      throw new Error("KolClaim projection tombstone conflicts with payload");
    }
    return {
      data,
      eventTime: pgInstant(row.event_time, "event_time"),
      availableTime: pgInstant(row.available_time, "available_time"),
      processingTime: pgInstant(row.processing_time, "processing_time"),
      sourceVersions: [sourceVersion(data.source, data.sourceVersion)],
      evidenceIds: data.evidence.map((item) => item.evidenceId),
    };
  });
}

export async function loadPersistedEvidence(
  client: Pick<PoolClient, "query">,
  evidenceIds: readonly string[],
  asOf: string,
): Promise<PitRecord<KolEvidence>[]> {
  if (evidenceIds.length === 0) return [];
  const result = await client.query<EvidenceRow>(EVIDENCE_SQL, [[...evidenceIds], asOf]);
  return result.rows.map((row) => {
    const data = validateKolEvidencePayload(row.payload);
    const source = pgText(row.source, "source");
    const version = pgText(row.source_version, "source_version");
    return {
      data,
      eventTime: data.contentAvailableTime,
      availableTime: pgInstant(row.available_time, "available_time"),
      processingTime: pgInstant(row.processing_time, "processing_time"),
      sourceVersions: [sourceVersion(source, version)],
      evidenceIds: [data.evidenceId],
    };
  });
}

export const SEAT_TRADE_PIT_SQL = SEAT_SQL;
export const KOL_CLAIM_PIT_SQL = CLAIM_SQL;
export const EVIDENCE_PIT_SQL = EVIDENCE_SQL;
