import type { Instrument } from "@kunlun/shared-types";
import type { PoolClient, QueryResultRow } from "pg";
import { pgInstant, pgText, sourceVersion } from "./pg-row";
import { validateInstrumentPayload } from "./pit-validation";
import type { PitRecord } from "./read-model.types";

interface InstrumentRow extends QueryResultRow {
  payload: unknown;
  effective_from: unknown;
  available_time: unknown;
  processing_time: unknown;
  source: unknown;
  source_version: unknown;
  evidence_id: unknown;
}

const SQL = [
  "SELECT payload, effective_from, available_time, processing_time,",
  "       source, source_version, evidence_id",
  "FROM instrument_master_revisions",
  "WHERE instrument_id = $1",
  "  AND effective_from <= $2::timestamptz",
  "  AND (effective_to IS NULL OR effective_to > $2::timestamptz)",
  "  AND available_time <= $2::timestamptz",
  "  AND processing_time <= $2::timestamptz",
  "ORDER BY effective_from DESC, available_time DESC, processing_time DESC, revision_id DESC",
  "LIMIT 1",
].join("\n");

export async function loadInstrumentMaster(
  client: Pick<PoolClient, "query">,
  instrumentId: string,
  asOf: string,
): Promise<PitRecord<Instrument> | null> {
  const result = await client.query<InstrumentRow>(SQL, [instrumentId, asOf]);
  const row = result.rows[0];
  if (!row) return null;
  const source = pgText(row.source, "source");
  const version = pgText(row.source_version, "source_version");
  return {
    data: validateInstrumentPayload(row.payload),
    eventTime: pgInstant(row.effective_from, "effective_from"),
    availableTime: pgInstant(row.available_time, "available_time"),
    processingTime: pgInstant(row.processing_time, "processing_time"),
    sourceVersions: [sourceVersion(source, version)],
    evidenceIds: [pgText(row.evidence_id, "evidence_id")],
  };
}

export const INSTRUMENT_MASTER_PIT_SQL = SQL;
