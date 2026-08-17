/**
 * PostgreSQL adapter for the quality repository port.
 *
 * Reads the data-worker's `fund_quality_events` tables. The semantic key is
 * `{endpoint_kind}:{unified_code}:{reference_date}`; the instrument code and
 * trading date are extracted with split_part so filters stay parameterized and
 * free of string interpolation. Evidence is joined through its link table and
 * only safe fields (source, schema version, availability) are selected —
 * never raw object ids, capture ids, checksums, or payload digests.
 */

import type { Pool } from "pg";

import { reasonForKind, type DataQualityRecord, type EvidenceRecord } from "./quality-record";
import type { QualityQuery, QualityRepository } from "./quality-repository";

interface QualityRow {
  id: string;
  kind: string;
  unified_code: string;
  reference_date: string;
  created_at: Date | string;
  source: string | null;
  schema_version: string | null;
  available_time: Date | string | null;
}

interface EvidenceRow {
  id: string;
  source: string;
  schema_version: string;
  available_time: Date | string | null;
}

const QUERY_SQL = `
SELECT
  qe.event_id AS id,
  qe.kind AS kind,
  split_part(qe.semantic_key, ':', 2) AS unified_code,
  split_part(qe.semantic_key, ':', 3) AS reference_date,
  qe.created_at AS created_at,
  ev.source AS source,
  ev.schema_version AS schema_version,
  ev.available_time AS available_time
FROM fund_quality_events qe
LEFT JOIN LATERAL (
  SELECT e.source, e.schema_version, e.available_time
  FROM fund_quality_event_evidence qee
  JOIN fund_observation_evidence e ON e.record_id = qee.evidence_id
  WHERE qee.quality_event_id = qe.event_id
  ORDER BY e.ingest_time ASC
  LIMIT 1
) ev ON true
WHERE ($1::text IS NULL OR split_part(qe.semantic_key, ':', 3) = $1)
  AND ($2::text IS NULL OR split_part(qe.semantic_key, ':', 3) >= $2)
  AND ($3::text IS NULL OR split_part(qe.semantic_key, ':', 3) <= $3)
  AND ($4::text IS NULL OR split_part(qe.semantic_key, ':', 2) = $4)
  AND ($5::text IS NULL OR qe.kind = $5)
  AND ($6::text IS NULL OR ev.source = $6)
ORDER BY qe.created_at DESC, qe.event_id ASC
`;

const EVIDENCE_SQL = `
SELECT
  e.record_id AS id,
  e.source AS source,
  e.schema_version AS schema_version,
  e.available_time AS available_time
FROM fund_quality_event_evidence qee
JOIN fund_observation_evidence e ON e.record_id = qee.evidence_id
WHERE qee.quality_event_id = $1
ORDER BY e.ingest_time ASC
LIMIT 1
`;

function toIsoString(value: Date | string | null): string | null {
  if (value === null) return null;
  if (value instanceof Date) return value.toISOString();
  return value;
}

export class PostgresQualityRepository implements QualityRepository {
  constructor(private readonly pool: Pool) {}

  async query(filters: QualityQuery): Promise<DataQualityRecord[]> {
    const params: (string | null)[] = [
      filters.date ?? null,
      filters.dateFrom ?? null,
      filters.dateTo ?? null,
      filters.unifiedCode ?? null,
      filters.kind ?? null,
      filters.source ?? null,
    ];
    const result = await this.pool.query<QualityRow>(QUERY_SQL, params);
    return result.rows.map((row) => ({
      id: row.id,
      kind: row.kind,
      unifiedCode: row.unified_code || null,
      date: row.reference_date,
      source: row.source,
      detail: reasonForKind(row.kind),
      createdAt: toIsoString(row.created_at) ?? "",
      availableAt: toIsoString(row.available_time),
      schemaVersion: row.schema_version ?? "",
    }));
  }

  async getEvidence(eventId: string): Promise<EvidenceRecord | null> {
    const result = await this.pool.query<EvidenceRow>(EVIDENCE_SQL, [eventId]);
    const row = result.rows[0];
    if (row === undefined) return null;
    return {
      id: row.id,
      source: row.source,
      schemaVersion: row.schema_version,
      availableAt: toIsoString(row.available_time),
    };
  }

  async close(): Promise<void> {
    await this.pool.end();
  }
}
